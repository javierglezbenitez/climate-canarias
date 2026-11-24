import * as duckdb from '@duckdb/duckdb-wasm';
import wasmEh from '@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url';
import workerEh from '@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url';

const FILES = ['annual_anomaly', 'trend_summary', 'decadal_anomaly_grid', 'trend_grid', 'monthly_anomaly'];
const OPTIONAL = ['lst_summer_grid', 'lst_summer_yearly'];
const loaded = new Set();
let conn = null;

export async function initDb() {
  const worker = new Worker(workerEh);
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(new URL(wasmEh, location.href).href);
  conn = await db.connect();
  const base = import.meta.env.BASE_URL;
  for (const name of FILES) {
    const res = await fetch(`${base}data/${name}.parquet`);
    if (!res.ok) throw new Error(`No se pudo cargar ${name}.parquet (${res.status})`);
    await db.registerFileBuffer(`${name}.parquet`, new Uint8Array(await res.arrayBuffer()));
    await conn.query(`CREATE TABLE ${name} AS SELECT * FROM '${name}.parquet'`);
    loaded.add(name);
  }
  // Capa de satélite: opcional (si faltan los ficheros, la web funciona sin ella)
  for (const name of OPTIONAL) {
    try {
      const res = await fetch(`${base}data/${name}.parquet`);
      if (!res.ok) continue;
      await db.registerFileBuffer(`${name}.parquet`, new Uint8Array(await res.arrayBuffer()));
      await conn.query(`CREATE TABLE ${name} AS SELECT * FROM '${name}.parquet'`);
      loaded.add(name);
    } catch (e) {
      console.warn(`Sin capa de satélite (${name})`, e);
    }
  }
}

/** Devuelve filas como objetos JS (BigInt -> Number). */
export async function sql(text) {
  const table = await conn.query(text);
  const cols = table.schema.fields.map((f) => f.name);
  const rows = table.toArray().map((r) => {
    const o = {};
    for (const c of cols) {
      const v = r[c];
      o[c] = typeof v === 'bigint' ? Number(v) : v;
    }
    return o;
  });
  return { cols, rows };
}

export async function loadAll() {
  const annual = (await sql('SELECT year, anomaly_c, complete FROM annual_anomaly ORDER BY year')).rows;
  const summary = (await sql('SELECT * FROM trend_summary')).rows[0];
  const decadal = (await sql('SELECT decade, n_years, latitude, longitude, anomaly_c FROM decadal_anomaly_grid')).rows;
  const trend = (await sql('SELECT latitude, longitude, trend_c_per_decade FROM trend_grid')).rows;
  let lst = null;
  if (loaded.has('lst_summer_grid') && loaded.has('lst_summer_yearly')) {
    lst = {
      grid: (await sql('SELECT latitude, longitude, lst_mean_c, lst_max_c, n_obs, n_total FROM lst_summer_grid')).rows,
      yearly: (await sql('SELECT year, lst_mean_c, n_scenes FROM lst_summer_yearly ORDER BY year')).rows,
    };
  }
  return { annual, summary, decadal, trend, lst };
}
