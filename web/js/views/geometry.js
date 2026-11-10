// Geometry helpers shared by the editor (mirrors src/occupancy.scale_polygon).

export function scalePolygon(polygon, fromSize, toSize) {
    const sx = toSize[0] / fromSize[0];
    const sy = toSize[1] / fromSize[1];
    return polygon.map(([x, y]) => [Math.round(x * sx), Math.round(y * sy)]);
}
