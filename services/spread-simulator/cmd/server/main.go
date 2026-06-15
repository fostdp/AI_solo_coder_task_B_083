package main

import (
	"context"
	"log"
	"net"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	pb "github.com/guji/spread-simulator/proto"
	"github.com/guji/spread-simulator/pkg/seir"
)

type spreadSimulatorServer struct {
	pb.UnimplementedSpreadSimulatorServer
}

func (s *spreadSimulatorServer) SimulateSpread(
	ctx context.Context,
	req *pb.SimulationRequest,
) (*pb.SimulationResponse, error) {
	if req == nil {
		return nil, status.Error(codes.InvalidArgument, "request cannot be nil")
	}
	if req.Days <= 0 {
		return nil, status.Error(codes.InvalidArgument, "days must be positive")
	}
	if len(req.InitialInfected) == 0 {
		return nil, status.Error(codes.InvalidArgument, "initial_infected cannot be empty")
	}

	layout := seir.ShelvesLayout{
		TotalShelves: int(req.ShelvesLayout.TotalShelves),
		Columns:      int(req.ShelvesLayout.Columns),
		Layers:       int(req.ShelvesLayout.Layers),
	}

	edgeParams := seir.EdgeWeightParams{
		DistanceFactor:       req.EdgeParams.DistanceFactor,
		VentilationFactor:    req.EdgeParams.VentilationFactor,
		AdjacencyBonus:       req.EdgeParams.AdjacencyBonus,
		VentilationDefault:   req.EdgeParams.VentilationDefault,
		ShelfDistanceDefault: req.EdgeParams.ShelfDistanceDefault,
	}

	graph := seir.NewShelfGraph(layout, edgeParams)

	seirParams := seir.SEIRParams{
		Beta:  req.SeirParams.Beta,
		Sigma: req.SeirParams.Sigma,
		Gamma: req.SeirParams.Gamma,
		Mu:    req.SeirParams.Mu,
	}

	results := seir.SimulateSpread(
		graph,
		req.InitialInfected,
		int(req.Days),
		seirParams,
		edgeParams,
	)

	hotspots := seir.IdentifyHotspots(results, 0.5)
	directions := graph.GetSpreadDirections()

	pbResults := make([]*pb.SimulationResult, len(results))
	for i, r := range results {
		pbResults[i] = &pb.SimulationResult{
			Day:     int32(r.Day),
			ShelfId: r.ShelfID,
			State: &pb.SEIRState{
				S:             r.State.S,
				E:             r.State.E,
				I:             r.State.I,
				R:             r.State.R,
				InfectionProb: r.State.InfectionProb(),
			},
			SpreadFrom: r.SpreadFrom,
			EdgeWeight: r.EdgeWeight,
		}
	}

	pbHotspots := make([]*pb.Hotspot, len(hotspots))
	for i, h := range hotspots {
		pbHotspots[i] = &pb.Hotspot{
			ShelfId:          h.ShelfID,
			MaxInfectionProb: h.MaxInfectionProb,
			FirstDay:         int32(h.FirstDay),
			IsHotspot:        h.IsHotspot,
		}
	}

	pbDirections := make([]*pb.Direction, len(directions))
	for i, d := range directions {
		pbDirections[i] = &pb.Direction{
			FromShelf: d.FromShelf,
			ToShelf:   d.ToShelf,
			Weight:    d.Weight,
		}
	}

	return &pb.SimulationResponse{
		Results:    pbResults,
		Hotspots:   pbHotspots,
		Directions: pbDirections,
	}, nil
}

func main() {
	lis, err := net.Listen("tcp", ":50051")
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}

	server := grpc.NewServer()
	pb.RegisterSpreadSimulatorServer(server, &spreadSimulatorServer{})

	log.Printf("Spread Simulator gRPC server starting on :50051")
	if err := server.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
