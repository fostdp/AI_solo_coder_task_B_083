package seir

import (
	"math"
	"sort"
)

type SEIRState struct {
	S float64
	E float64
	I float64
	R float64
}

func (s *SEIRState) InfectionProb() float64 {
	return s.E + s.I
}

type SEIRParams struct {
	Beta  float64
	Sigma float64
	Gamma float64
	Mu    float64
}

type SEIRModel struct {
	beta  float64
	sigma float64
	gamma float64
	mu    float64
}

func NewSEIRModel(params SEIRParams) *SEIRModel {
	model := &SEIRModel{
		beta:  params.Beta,
		sigma: params.Sigma,
		gamma: params.Gamma,
		mu:    params.Mu,
	}
	if model.beta == 0 {
		model.beta = 0.3
	}
	if model.sigma == 0 {
		model.sigma = 0.2
	}
	if model.gamma == 0 {
		model.gamma = 0.1
	}
	if model.mu == 0 {
		model.mu = 0.01
	}
	return model
}

func (m *SEIRModel) Step(state SEIRState, infectionPressure float64) SEIRState {
	S := state.S
	E := state.E
	I := state.I
	R := state.R

	effectiveBeta := m.beta * (I + infectionPressure)

	new_S := S - effectiveBeta*S*I + m.mu*(1-S)
	new_E := E + effectiveBeta*S*I - (m.sigma + m.mu)*E
	new_I := I + m.sigma*E - (m.gamma + m.mu)*I
	new_R := R + m.gamma*I - m.mu*R

	new_S = math.Max(0.0, math.Min(1.0, new_S))
	new_E = math.Max(0.0, math.Min(1.0, new_E))
	new_I = math.Max(0.0, math.Min(1.0, new_I))
	new_R = math.Max(0.0, math.Min(1.0, new_R))

	total := new_S + new_E + new_I + new_R
	if total > 0 {
		new_S /= total
		new_E /= total
		new_I /= total
		new_R /= total
	}

	return SEIRState{S: new_S, E: new_E, I: new_I, R: new_R}
}

type SimulationResult struct {
	Day         int
	ShelfID     string
	State       SEIRState
	SpreadFrom  string
	EdgeWeight  float64
}

type Hotspot struct {
	ShelfID           string
	MaxInfectionProb  float64
	FirstDay          int
	IsHotspot         bool
}

type spreadSource struct {
	spreadFrom string
	edgeWeight float64
}

func SimulateSpread(
	graph *ShelfGraph,
	initialInfected []string,
	days int,
	seirParams SEIRParams,
	edgeParams EdgeWeightParams,
) []*SimulationResult {
	model := NewSEIRModel(seirParams)

	states := make(map[string]SEIRState)

	shelfIDs := make([]string, 0, len(graph.Nodes))
	for id := range graph.Nodes {
		shelfIDs = append(shelfIDs, id)
	}
	sort.Strings(shelfIDs)

	initialInfectedSet := make(map[string]bool)
	for _, id := range initialInfected {
		initialInfectedSet[id] = true
	}

	for _, shelfID := range shelfIDs {
		if initialInfectedSet[shelfID] {
			states[shelfID] = SEIRState{S: 0.0, E: 0.0, I: 1.0, R: 0.0}
		} else {
			states[shelfID] = SEIRState{S: 1.0, E: 0.0, I: 0.0, R: 0.0}
		}
	}

	results := make([]*SimulationResult, 0)

	for day := 1; day <= days; day++ {
		newStates := make(map[string]SEIRState)
		spreadSources := make(map[string]spreadSource)

		for _, shelfID := range shelfIDs {
			currentState := states[shelfID]
			infectionPressure := 0.0
			maxWeight := 0.0
			spreadFrom := ""

			for _, neighbor := range graph.GetNeighbors(shelfID) {
				neighborState := states[neighbor.ShelfID]
				neighborI := neighborState.I
				pressure := neighborI * neighbor.Weight
				infectionPressure += pressure

				if pressure > maxWeight && neighborI > 0.1 {
					maxWeight = neighbor.Weight
					spreadFrom = neighbor.ShelfID
				}
			}

			newState := model.Step(currentState, infectionPressure)
			newStates[shelfID] = newState

			if spreadFrom != "" && (newState.E > 0.01 || newState.I > 0.01) {
				spreadSources[shelfID] = spreadSource{
					spreadFrom: spreadFrom,
					edgeWeight: maxWeight,
				}
			}
		}

		for _, shelfID := range shelfIDs {
			newState := newStates[shelfID]
			source := spreadSources[shelfID]
			result := &SimulationResult{
				Day:        day,
				ShelfID:    shelfID,
				State:      newState,
				SpreadFrom: source.spreadFrom,
				EdgeWeight: source.edgeWeight,
			}
			results = append(results, result)
		}

		states = newStates
	}

	return results
}

func IdentifyHotspots(simulationResults []*SimulationResult, threshold float64) []*Hotspot {
	shelfMaxInfection := make(map[string]*Hotspot)

	for _, result := range simulationResults {
		shelfID := result.ShelfID
		infectionProb := result.State.InfectionProb()

		if _, exists := shelfMaxInfection[shelfID]; !exists {
			shelfMaxInfection[shelfID] = &Hotspot{
				ShelfID:          shelfID,
				MaxInfectionProb: 0.0,
				FirstDay:         0,
				IsHotspot:        false,
			}
		}

		if infectionProb > shelfMaxInfection[shelfID].MaxInfectionProb {
			shelfMaxInfection[shelfID].MaxInfectionProb = infectionProb
		}

		if infectionProb >= threshold && shelfMaxInfection[shelfID].FirstDay == 0 {
			shelfMaxInfection[shelfID].FirstDay = result.Day
			shelfMaxInfection[shelfID].IsHotspot = true
		}
	}

	hotspots := make([]*Hotspot, 0)
	for _, info := range shelfMaxInfection {
		if info.IsHotspot {
			hotspots = append(hotspots, info)
		}
	}

	sort.Slice(hotspots, func(i, j int) bool {
		return hotspots[i].MaxInfectionProb > hotspots[j].MaxInfectionProb
	})

	return hotspots
}
