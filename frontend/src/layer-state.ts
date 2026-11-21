// The map layers the sidebar switches on and off.
export interface LayerState {
  basemap: 'osm' | 'topo' | 'satellite';
  fields: boolean;
  risks: boolean;
  ownParcels: boolean;
}

