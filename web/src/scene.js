import { Deck, MapView, FlyToInterpolator } from '@deck.gl/core';
import { ColumnLayer, TextLayer } from '@deck.gl/layers';
import { TerrainLayer } from '@deck.gl/geo-layers';
import { _TerrainExtension as TerrainExtension } from '@deck.gl/extensions';
import { diverging } from './colors.js';

// Relieve: teselas Terrarium (AWS Open Data, sin clave). Textura: Esri Canvas World Dark Gray Base (sin clave).
export const TEXTURE_URL = 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
export const DEM_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';

const ISLANDS = [
  { name: 'Lanzarote', lon: -13.75, lat: 28.8 },
  { name: 'Fuerteventura', lon: -14.0, lat: 28.15 },
  { name: 'Gran Canaria', lon: -15.6, lat: 27.6 },
  { name: 'Tenerife', lon: -16.55, lat: 27.95 },
  { name: 'La Gomera', lon: -17.12, lat: 27.85 },
  { name: 'La Palma', lon: -17.85, lat: 28.42 },
  { name: 'El Hierro', lon: -18.0, lat: 27.52 },
];

const EXAGGERATION = 3;
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

export const SCALE = { decade: 1.2, trend: 0.2 }; // valor que satura la escala de color

function viewFor(width) {
  const narrow = width < 700;
  return {
    longitude: -15.85,
    latitude: 28.3,
    zoom: narrow ? 6.4 : 7.6,
    pitch: 55,
    bearing: -18,
    minZoom: 5.5,
    maxZoom: 11,
    maxPitch: 75,
  };
}

export function createScene({ parent, onHover }) {
  let state = { cells: [], mode: 'decade', label: '' };
  let hovered = null;

  const terrain = new TerrainLayer({
    id: 'terrain',
    minZoom: 0,
    maxZoom: 12,
    elevationData: DEM_URL,
    texture: TEXTURE_URL,
    elevationDecoder: {
      rScaler: 256 * EXAGGERATION,
      gScaler: 1 * EXAGGERATION,
      bScaler: (1 / 256) * EXAGGERATION,
      offset: -32768 * EXAGGERATION,
    },
    material: { ambient: 0.55, diffuse: 0.6, shininess: 4, specularColor: [30, 40, 45] },
    operation: 'terrain+draw',
    color: [255, 255, 255],
  });

  const layers = () => {
    const max = SCALE[state.mode];
    return [
      terrain,
      new ColumnLayer({
        id: 'cells',
        data: state.cells,
        extensions: [new TerrainExtension()],
        terrainDrawMode: 'offset',
        diskResolution: 6,
        radius: 4300,
        extruded: true,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 90],
        getPosition: (d) => [d.lon, d.lat],
        getElevation: (d) => Math.max(500, (d.value + (state.mode === 'decade' ? 0.8 : 0.05)) * (state.mode === 'decade' ? 11000 : 60000)),
        getFillColor: (d) => [...diverging(d.value, max), 235],
        material: { ambient: 0.5, diffuse: 0.7, shininess: 20 },
        transitions: reduceMotion ? {} : { getElevation: 700, getFillColor: 700 },
        updateTriggers: { getElevation: [state.mode, state.label], getFillColor: [state.mode, state.label] },
      }),
      new TextLayer({
        id: 'names',
        data: ISLANDS,
        extensions: [new TerrainExtension()],
        terrainDrawMode: 'offset',
        getPosition: (d) => [d.lon, d.lat],
        getText: (d) => d.name,
        getSize: 14,
        getColor: [238, 243, 244, 235],
        fontFamily: 'system-ui, "Segoe UI", sans-serif',
        fontWeight: 600,
        outlineWidth: 4,
        outlineColor: [11, 29, 38, 230],
        fontSettings: { sdf: true },
        billboard: true,
        pickable: false,
        parameters: { depthCompare: 'always', depthWriteEnabled: false },
      }),
    ];
  };

  const deck = new Deck({
    parent,
    views: new MapView({ repeat: false }),
    initialViewState: reduceMotion
      ? viewFor(parent.clientWidth || innerWidth)
      : { ...viewFor(parent.clientWidth || innerWidth), zoom: 5.4, pitch: 0, bearing: 0, longitude: -15.9, latitude: 28.5 },
    controller: { dragRotate: true, touchRotate: true, keyboard: true },
    layers: layers(),
    parameters: { clearColor: [0.043, 0.114, 0.149, 1] },
    onHover: (info) => {
      hovered = info.object || null;
      onHover(info.object ? { ...info.object, x: info.x, y: info.y } : null);
    },
    getCursor: ({ isDragging }) => (isDragging ? 'grabbing' : hovered ? 'pointer' : 'grab'),
  });

  return {
    deck,
    update(next) {
      state = { ...state, ...next };
      deck.setProps({ layers: layers() });
    },
    intro() {
      if (reduceMotion) return;
      deck.setProps({
        initialViewState: {
          ...viewFor(parent.clientWidth || innerWidth),
          transitionDuration: 4200,
          transitionInterpolator: new FlyToInterpolator({ curve: 1.2 }),
        },
      });
    },
    reset() {
      deck.setProps({ initialViewState: { ...viewFor(parent.clientWidth || innerWidth), transitionDuration: reduceMotion ? 0 : 1200 } });
    },
  };
}
