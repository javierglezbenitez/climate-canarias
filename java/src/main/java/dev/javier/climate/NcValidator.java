package dev.javier.climate;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import ucar.ma2.Array;
import ucar.nc2.Variable;
import ucar.nc2.dataset.NetcdfDataset;
import ucar.nc2.dataset.NetcdfDatasets;

/**
 * Puerta de calidad para ficheros ERA5-Land en NetCDF.
 *
 * Comprueba estructura (variable t2m, dimensiones de tiempo/lat/lon), rango físico
 * plausible (en kelvin) y proporción de valores vacíos. Devuelve código de salida
 * 0 si el fichero es válido y 1 si no, para poder usarlo en un Job de Kubernetes
 * o en CI antes de pasar de la capa bronze a la silver.
 */
public final class NcValidator {

    private static final String VARIABLE = "t2m";
    // Rango plausible de temperatura a 2 m en Canarias (K): -20 °C .. 50 °C
    private static final float MIN_K = 253.15f;
    private static final float MAX_K = 323.15f;
    // ERA5-Land no tiene datos sobre el mar, así que se tolera una parte vacía
    private static final double MAX_MISSING_RATIO = 0.98;

    private NcValidator() {}

    public static void main(String[] args) {
        if (args.length != 1) {
            System.err.println("Uso: java -jar nc-validator.jar <fichero.nc>");
            System.exit(2);
        }
        try {
            List<String> errors = validate(args[0]);
            if (errors.isEmpty()) {
                System.out.println("RESULTADO: OK");
                System.exit(0);
            }
            System.out.println("RESULTADO: FALLO");
            errors.forEach(e -> System.out.println(" - " + e));
            System.exit(1);
        } catch (IOException e) {
            System.err.println("No se pudo leer el fichero: " + e.getMessage());
            System.exit(2);
        }
    }

    static List<String> validate(String path) throws IOException {
        List<String> errors = new ArrayList<>();

        try (NetcdfDataset ds = NetcdfDatasets.openDataset(path)) {
            System.out.println("Fichero: " + path);
            System.out.println("Dimensiones: " + ds.getDimensions());

            Variable v = ds.findVariable(VARIABLE);
            if (v == null) {
                errors.add("No existe la variable '" + VARIABLE + "'");
                return errors;
            }

            boolean hasTime = ds.findDimension("valid_time") != null || ds.findDimension("time") != null;
            boolean hasLat = ds.findDimension("latitude") != null || ds.findDimension("lat") != null;
            boolean hasLon = ds.findDimension("longitude") != null || ds.findDimension("lon") != null;
            if (!hasTime) errors.add("Falta la dimensión de tiempo (valid_time/time)");
            if (!hasLat) errors.add("Falta la dimensión de latitud");
            if (!hasLon) errors.add("Falta la dimensión de longitud");

            Array data = v.read(); // aplica scale_factor/add_offset y convierte missing a NaN
            long total = data.getSize();
            long missing = 0;
            double sum = 0;
            float min = Float.POSITIVE_INFINITY;
            float max = Float.NEGATIVE_INFINITY;

            for (int i = 0; i < total; i++) {
                float x = data.getFloat(i);
                if (Float.isNaN(x)) {
                    missing++;
                    continue;
                }
                sum += x;
                if (x < min) min = x;
                if (x > max) max = x;
            }

            long valid = total - missing;
            double missingRatio = total == 0 ? 1.0 : (double) missing / total;

            System.out.printf("Valores totales: %d, válidos: %d (%.1f%% vacíos)%n", total, valid, missingRatio * 100);
            if (valid > 0) {
                System.out.printf("t2m min/media/max: %.2f / %.2f / %.2f °C%n",
                        min - 273.15, sum / valid - 273.15, max - 273.15);
            }

            if (total == 0) errors.add("La variable no contiene datos");
            if (valid == 0) {
                errors.add("Todos los valores están vacíos");
            } else {
                if (min < MIN_K || max > MAX_K) {
                    errors.add(String.format("Valores fuera de rango físico plausible: %.2f..%.2f K", min, max));
                }
                if (missingRatio > MAX_MISSING_RATIO) {
                    errors.add(String.format("Demasiados valores vacíos: %.1f%%", missingRatio * 100));
                }
            }
        }
        return errors;
    }
}
