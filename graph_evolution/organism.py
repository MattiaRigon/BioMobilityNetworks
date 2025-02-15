from collections import deque
from copy import deepcopy
from random import randint, random, sample
from scipy.stats import norm
from scipy.integrate import quad
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

import eval_functions as ef


# this function is based on:
# Clifford Bohm, Arend Hintze, Jory Schossau; July 24–28, 2023.
# "A Simple Sparsity Function to Promote Evolutionary Search." 
# Proceedings of the ALIFE 2023: Ghost in the Machine: 
# Proceedings of the 2023 Artificial Life Conference. 
# ALIFE 2023: Ghost in the Machine: Proceedings of the 2023 Artificial Life Conference. 
# Online. (pp. 53). ASME. https://doi.org/10.1162/isal_a_00655
def sparsify(x, percentSparse:float = 0.5, outputRange:tuple[float]=(-1,1)):
    # assert 0 <= percentSparse <= 1
    # assert outputRange[0] <= 0 <= outputRange[1]
    # assert outputRange[0] != 0 or outputRange[1] != 0

    percentNonZero = 1-percentSparse
    neg = abs(outputRange[0])
    pos = outputRange[1]
    negPercent = neg/(pos+neg)
    posPercent = pos/(pos+neg)
    a = negPercent*percentNonZero
    b = posPercent*percentNonZero
    t1 = a
    t2 = a + percentSparse

    if x <= 0:
        return -neg
    elif 0 < x <= t1:
        return (neg/a)*x- neg
    elif t1 < x <= t2:
        return 0
    elif t2 < x <= 1:
        return (pos/b)*(x-t2)
    else: #1 < x:
        return pos


class Organism:
    nextID = 0

    def __init__(self, numNodes:int, sparsity:float, weightRange, genome:list[list[float]]=None, age=0) -> None:
        self.id = Organism.nextID
        Organism.nextID += 1
        self.nsga_rank = None
        self.nsga_distance = None
        self.age = age
        self.clock = -1

        if genome is None:
            self.genotypeMatrix:list[list[float]] = [[random() for _ in range(numNodes)] for _ in range(numNodes)]
        else:
            self.genotypeMatrix:list[list[float]] = genome

        self.numNodes:int = numNodes
        self.sparsity = sparsity
        self.weightRange = weightRange

        self.errors:dict[str:float] = {}
        self.properties:dict = {}

        self.adjacencyMatrix:list[list[float]] = [[round(sparsify(val, self.sparsity, self.weightRange), 3) for val in row] for row in self.genotypeMatrix]
    
        #internal validity tracker - must be strongly connected
        self.valid = True #len(list(nx.strongly_connected_components(self.getNetworkxObject()))) == 1

        #internal number of interactions reference
        self.numInteractions:int = sum([sum([1 for val in row if val != 0]) for row in self.adjacencyMatrix])
        #internal number of positive interactions reference
        self.numPositive:int = sum([sum([1 for val in row if val > 0]) for row in self.adjacencyMatrix])
        #internal number of negative interactions reference
        self.numNegative:int = sum([sum([1 for val in row if val < 0]) for row in self.adjacencyMatrix])


    def makeMutatedCopy(self, mutationRate:float, mutationOdds:tuple[int]):
        #setup
        mutationThresholds = [sum(mutationOdds[:k+1]) for k in range(len(mutationOdds))]
        #inheritance
        newGenome = deepcopy(self.genotypeMatrix)
        #variation
        for i in range(self.numNodes):
            for j in range(self.numNodes):
                if random() <= mutationRate:
                    mutationType = randint(1,sum(mutationOdds))
                    if mutationType <= mutationThresholds[0]:
                        #point mutation
                        newGenome[i][j] = random()
                    elif mutationType <= mutationThresholds[1]:
                        #offset mutation
                        offset = (random()/4)-(1/8) #-1/8 to 1/8
                        newGenome[i][j] = min(1,max(0,newGenome[i][j] + offset))
                    elif mutationType <= mutationThresholds[2]:
                        #sign flip mutation
                        newGenome[i][j] = 1-newGenome[i][j]
                    elif mutationType <= mutationThresholds[3]:
                        #weight swap mutation (preserves connectance)
                        edge1= newGenome[i][j]
                        iswap = randint(0,self.numNodes-1)
                        jswap = randint(0,self.numNodes-1)
                        newGenome[i][j] = newGenome[iswap][jswap]
                        newGenome[iswap][jswap] = edge1
                    else:
                        print("ERROR: no mutation selected")
                        exit(1)
        # sometimes add random offset to sparsity and clamp to [0,1]
        newSparsity = self.sparsity if random() > mutationRate else min(1,max(0,self.sparsity + (random()/4)-(1/8)))
        return Organism(self.numNodes, newSparsity, self.weightRange, newGenome, self.age)

    
    def xover_traversal_helper(self, other, rateFromOther, algorithm):
        N = len(other.genotypeMatrix)
        if algorithm == "DFS":
            visited = []
        elif algorithm == "BFS":
            visited = deque()
        else: raise Exception("invalid traversal algorithm")
        completed = []
        available = [i for i in range(N)]
        while random() <= rateFromOther and len(completed) < N and available:
            currentNode = sample(available,k=1)[0]
            visited.append(currentNode)
            available = [i for i in range(N)
                            if other.adjacencyMatrix[currentNode][i] != 0 and
                            i not in visited and
                            i not in completed]
            while not available and len(completed) < N and visited:
                completed.append(currentNode)
                if algorithm == "DFS":
                    currentNode = visited.pop()
                elif algorithm == "BFS":
                    currentNode = visited.popleft()
                available = [i for i in range(N)
                            if other.adjacencyMatrix[currentNode][i] != 0 and
                            i not in visited and
                            i not in completed]
        return list(visited) + completed


    def makeCrossedCopyWith(self, other, rateFromOther, crossOdds:tuple[int], generation:int):
        #age updating
        if self.clock < generation:
            self.age += 1
            self.clock = generation
        if other.clock < generation:
            other.age += 1
            other.clock = generation
        #setup
        crossoverThresholds = [sum(crossOdds[:k+1]) for k in range(len(crossOdds))]
        crossoverType = randint(1, sum(crossOdds))
        #inheritance
        newGenome = deepcopy(self.genotypeMatrix)
        #crossover
        if crossoverType <= crossoverThresholds[0]:
            #binary node crossover
            for i in range(self.numNodes):
                if random() <= rateFromOther:
                    newGenome[i] = deepcopy(other.genotypeMatrix[i])
        elif crossoverType <= crossoverThresholds[1]:
            #depth-first-traversal crossover
            crossNodes = self.xover_traversal_helper(other, rateFromOther, "DFS")
            for i in crossNodes:
                newGenome[i] = deepcopy(other.genotypeMatrix[i])
        elif crossoverType <= crossoverThresholds[2]:
            #breadth-first-traversal crossover
            crossNodes = self.xover_traversal_helper(other, rateFromOther, "BFS")
            for i in crossNodes:
                newGenome[i] = deepcopy(other.genotypeMatrix[i])
        #return child, +1 on child age implicit in +1 on both parents above
        return Organism(self.numNodes, self.sparsity, self.weightRange, newGenome, max(self.age, other.age))


    def getProperty(self, propertyName:str):
        if propertyName not in self.properties:
            self.properties[propertyName] = ef.functions[propertyName](None,self)
        return self.properties[propertyName]

    
    def getError(self, propertyName:str, target, _range=None) -> float:
        if propertyName not in self.errors:
            if propertyName.endswith("_distribution"):
                dist = self.getProperty(propertyName)
                self.errors[propertyName] = sum([(dist[i]-target[i])**2 for i in range(len(dist))])
                if _range is not None:
                    #update feasibility
                    self.check_constraints_distribution(dist,target, _range)
                    # if self.valid:
                    #     print("SIUM")
            elif propertyName in ["topology", "weights"]:
                mean, std = self.getProperty(propertyName)
                mean_error = (mean - target)**2
                std_error = (std - _range)**2
                self.errors[propertyName] = mean_error + std_error
                if _range is not None:
                    #update feasibility
                    self.check_constraint(mean, target, std , _range)
                    # if self.valid:
                    #     print("SIUM")



            else:
                self.errors[propertyName] = (self.getProperty(propertyName) - target)**2

        return self.errors[propertyName]


    def getNetworkxObject(self) -> nx.DiGraph:
        G = nx.DiGraph(np.array(self.adjacencyMatrix))
        return G


    def saveGraphFigure(self, path:str):
        G = self.getNetworkxObject()
        ######################
        # grpah layout style #
        ######################
        # pos = nx.nx_agraph.graphviz_layout(G)
        # pos = nx.kamada_kawai_layout(G)
        # pos = nx.spectral_layout(G)
        # pos = nx.planar_layout(G)
        # random
        pos = nx.shell_layout(G)
        # pos = nx.spring_layout(G)
        ######################

        plt.figure(figsize=(20,20))
        plt.title("Network Topology")

        nx.draw_networkx_nodes(G, pos=pos)
        nx.draw_networkx_labels(G, pos,
                                {node:node for node in G.nodes()},
                                font_size=9,
                                font_color="k")
        
        weights = nx.get_edge_attributes(G, 'weight').values()
        nx.draw_networkx_edges(G, pos=pos, edge_color=weights, width=5, edge_cmap=plt.cm.PuOr, edge_vmin=-1, edge_vmax=1)
        nx.draw_networkx_edge_labels(G, pos=pos,
                                     edge_labels={(n1,n2):round(data['weight'],3) for n1,n2,data in G.edges(data=True)},
                                     label_pos=0.8)

        plt.savefig(path)
        plt.close()


    ###########################
    #pareto sorting functions #
    ###########################
    def __gt__(self, other):
        #NOTE: potential confusion, gtr defines 'better' based on having smallest score
        someSelfBetter = False
        for prop in self.errors:
            self_error = self.errors[prop]
            other_error = other.errors[prop]
            if self_error > other_error:
                return False
            elif self_error < other_error:
                someSelfBetter = True
        return someSelfBetter


    def __eq__(self, other):
        return not (self < other or self > other)
    
    def check_constraints_distribution(self, dist, mean, std, eps = 0.2):
        
        sigma = 2
        num_invalid = 0
        for i,value in enumerate(dist):
            if value < mean[i] - sigma*std[i] or value > mean[i] + sigma*std[i]:
                num_invalid += 1
        
        if num_invalid/len(dist) > eps:
            self.valid = False
            

    def intersecting_area(self, mu1, sigma1, mu2, sigma2):
        """
        Calculate the intersecting area of two normal distributions.
        
        Parameters:
        - mu1: Mean of the first normal distribution
        - sigma1: Standard deviation of the first normal distribution
        - mu2: Mean of the second normal distribution
        - sigma2: Standard deviation of the second normal distribution
        
        Returns:
        - area: The intersecting area of the two distributions
        """
        # Define the PDFs of the two normal distributions
        pdf1 = lambda x: norm.pdf(x, mu1, sigma1)
        pdf2 = lambda x: norm.pdf(x, mu2, sigma2)
        
        # Define the minimum of the two PDFs
        min_pdf = lambda x: np.minimum(pdf1(x), pdf2(x))
        
        # Integrate the minimum PDF over the entire range
        # Choose a wide enough range to include most of the distributions' mass
        x_min = min(mu1 - 5 * sigma1, mu2 - 5 * sigma2)
        x_max = max(mu1 + 5 * sigma1, mu2 + 5 * sigma2)
        
        area, _ = quad(min_pdf, x_min, x_max)
        return area

    def check_constraint(self, mean, target_mean, std, target_std, eps = 0.75):
        
        intersection = self.intersecting_area(mean, std, target_mean, target_std)
        
        iou = intersection / (2 - intersection) # intersection over union
       
        if iou < eps:
            self.valid = False