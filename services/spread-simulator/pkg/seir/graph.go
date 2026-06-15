package seir

import (
	"fmt"
	"math"
)

type ShelfNode struct {
	ShelfID     string
	Row         int
	Col         int
	Layer       int
	Position    [3]int
	Ventilation float64
}

type Edge struct {
	FromShelf   string
	ToShelf     string
	Weight      float64
	Distance    float64
	Ventilation float64
}

type EdgeWeightParams struct {
	DistanceFactor       float64
	VentilationFactor    float64
	AdjacencyBonus       float64
	VentilationDefault   float64
	ShelfDistanceDefault float64
}

type ShelvesLayout struct {
	TotalShelves int
	Columns      int
	Layers       int
}

type ShelfGraph struct {
	ShelfLayout ShelvesLayout
	EdgeParams  EdgeWeightParams
	Nodes       map[string]*ShelfNode
	Edges       []*Edge
	Adjacency   map[string][]*Neighbor
}

type Neighbor struct {
	ShelfID string
	Weight  float64
}

func NewShelfGraph(layout ShelvesLayout, edgeParams EdgeWeightParams) *ShelfGraph {
	graph := &ShelfGraph{
		ShelfLayout: layout,
		EdgeParams:  edgeParams,
		Nodes:       make(map[string]*ShelfNode),
		Edges:       make([]*Edge, 0),
		Adjacency:   make(map[string][]*Neighbor),
	}
	graph.BuildGraph()
	return graph
}

func (g *ShelfGraph) BuildGraph() {
	totalShelves := g.ShelfLayout.TotalShelves
	if totalShelves == 0 {
		totalShelves = 10
	}
	cols := g.ShelfLayout.Columns
	if cols == 0 {
		cols = 5
	}
	layers := g.ShelfLayout.Layers
	if layers == 0 {
		layers = 6
	}

	ventilationDefault := g.EdgeParams.VentilationDefault
	if ventilationDefault == 0 {
		ventilationDefault = 0.5
	}
	distanceDefault := g.EdgeParams.ShelfDistanceDefault
	if distanceDefault == 0 {
		distanceDefault = 1.0
	}

	for i := 0; i < totalShelves; i++ {
		shelfID := fmt.Sprintf("SHELF-%02d", i+1)
		row := i / cols
		col := i % cols
		layer := 0

		node := &ShelfNode{
			ShelfID:     shelfID,
			Row:         row,
			Col:         col,
			Layer:       layer,
			Position:    [3]int{row, col, layer},
			Ventilation: ventilationDefault,
		}
		g.Nodes[shelfID] = node
		g.Adjacency[shelfID] = make([]*Neighbor, 0)
	}

	shelfIDs := make([]string, 0, len(g.Nodes))
	for id := range g.Nodes {
		shelfIDs = append(shelfIDs, id)
	}

	for i, fromID := range shelfIDs {
		fromNode := g.Nodes[fromID]
		for j := i + 1; j < len(shelfIDs); j++ {
			toID := shelfIDs[j]
			toNode := g.Nodes[toID]
			distance := g.computeDistance(fromNode.Position, toNode.Position, distanceDefault)

			if distance <= 2.0 {
				avgVentilation := (fromNode.Ventilation + toNode.Ventilation) / 2.0
				weight := ComputeEdgeWeight(distance, avgVentilation, g.EdgeParams)

				edge := &Edge{
					FromShelf:   fromID,
					ToShelf:     toID,
					Weight:      weight,
					Distance:    distance,
					Ventilation: avgVentilation,
				}
				g.Edges = append(g.Edges, edge)
				g.Adjacency[fromID] = append(g.Adjacency[fromID], &Neighbor{ShelfID: toID, Weight: weight})
				g.Adjacency[toID] = append(g.Adjacency[toID], &Neighbor{ShelfID: fromID, Weight: weight})
			}
		}
	}
}

func (g *ShelfGraph) computeDistance(pos1, pos2 [3]int, defaultDistance float64) float64 {
	dRow := math.Abs(float64(pos1[0] - pos2[0]))
	dCol := math.Abs(float64(pos1[1] - pos2[1]))
	dLayer := math.Abs(float64(pos1[2] - pos2[2]))

	if dRow == 0 && dCol == 0 && dLayer == 0 {
		return 0.0
	}

	distance := math.Sqrt(dRow*dRow + dCol*dCol + dLayer*dLayer)
	return math.Max(distance, defaultDistance)
}

func ComputeEdgeWeight(distance, ventilation float64, params EdgeWeightParams) float64 {
	distanceFactor := params.DistanceFactor
	if distanceFactor == 0 {
		distanceFactor = 0.01
	}
	ventilationFactor := params.VentilationFactor
	if ventilationFactor == 0 {
		ventilationFactor = 0.7
	}
	adjacencyBonus := params.AdjacencyBonus
	if adjacencyBonus == 0 {
		adjacencyBonus = 1.5
	}

	distanceTerm := math.Exp(-distanceFactor * distance)
	ventilationTerm := ventilationFactor*ventilation + (1 - ventilationFactor)
	weight := distanceTerm * ventilationTerm * adjacencyBonus

	return math.Max(0.0, math.Min(1.0, weight))
}

func (g *ShelfGraph) GetNeighbors(shelfID string) []*Neighbor {
	return g.Adjacency[shelfID]
}

func (g *ShelfGraph) GetSpreadDirections() []*Direction {
	directions := make([]*Direction, 0, len(g.Edges))
	for _, e := range g.Edges {
		directions = append(directions, &Direction{
			FromShelf: e.FromShelf,
			ToShelf:   e.ToShelf,
			Weight:    e.Weight,
		})
	}
	return directions
}

type Direction struct {
	FromShelf string
	ToShelf   string
	Weight    float64
}
