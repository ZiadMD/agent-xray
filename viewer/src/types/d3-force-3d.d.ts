// Minimal typings for the parts of d3-force-3d we use (the package ships none).
declare module 'd3-force-3d' {
  export interface SimulationNodeDatum {
    index?: number
    x?: number
    y?: number
    z?: number
    vx?: number
    vy?: number
    vz?: number
    fx?: number | null
    fy?: number | null
    fz?: number | null
  }

  export interface SimulationLinkDatum<N> {
    source: N | string
    target: N | string
    index?: number
  }

  type Accessor<T, R> = R | ((datum: T) => R)

  export interface Force<N> {
    (alpha: number): void
  }

  export interface Simulation<N extends SimulationNodeDatum> {
    tick(iterations?: number): this
    stop(): this
    nodes(): N[]
    force(name: string, force: Force<N> | null): this
    randomSource(source: () => number): this
  }

  export interface LinkForce<N, L> extends Force<N> {
    id(id: (node: N) => string): this
    distance(distance: Accessor<L, number>): this
    strength(strength: Accessor<L, number>): this
  }

  export interface ManyBodyForce<N> extends Force<N> {
    strength(strength: Accessor<N, number>): this
    distanceMax(distance: number): this
  }

  export interface CollideForce<N> extends Force<N> {
    radius(radius: Accessor<N, number>): this
    strength(strength: number): this
  }

  export interface PositionForce<N> extends Force<N> {
    strength(strength: Accessor<N, number>): this
  }

  export function forceSimulation<N extends SimulationNodeDatum>(
    nodes?: N[],
    numDimensions?: 1 | 2 | 3,
  ): Simulation<N>
  export function forceLink<N, L extends SimulationLinkDatum<N>>(links?: L[]): LinkForce<N, L>
  export function forceManyBody<N>(): ManyBodyForce<N>
  export function forceCollide<N>(radius?: Accessor<N, number>): CollideForce<N>
  export function forceX<N>(x?: Accessor<N, number>): PositionForce<N>
  export function forceY<N>(y?: Accessor<N, number>): PositionForce<N>
  export function forceZ<N>(z?: Accessor<N, number>): PositionForce<N>
}
