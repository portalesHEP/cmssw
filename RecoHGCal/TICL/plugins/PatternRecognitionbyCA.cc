// Author: Felice Pantaleo - felice.pantaleo@cern.ch
// Date: 11/2018
// Copyright CERN
#include <vector>
#include <set>
#include <algorithm>

#include "RecoHGCal/TICL/interface/TICLConstants.h"
#include "PatternRecognitionbyCA.h"

void PatternRecognitionbyCA::fillHistogram(const std::vector<reco::CaloCluster> &layerClusters,
                                           const std::vector<std::pair<unsigned int, float>> &mask)
{
    std::cout << "filling eta/phi histogram per Layer" << std::endl;
    for (auto &m : mask)
    {
        auto lcId = m.first;
        const auto &lc = layerClusters[lcId];
        //getting the layer Id from the detId of the first hit of the layerCluster
        const auto firstHitDetId = lc.hitsAndFractions()[0].first;
        int layer = rhtools_.getLayerWithOffset(firstHitDetId) + ticlConstants::maxNumberOfLayers * ((rhtools_.zside(firstHitDetId) + 1) >> 1) - 1;
        assert(layer >= 0);
        auto etaBin = getEtaBin(lc.eta());
        auto phiBin = getPhiBin(lc.phi());
        histogram_[layer][globalBin(etaBin, phiBin)].push_back(lcId);
    }
}

void PatternRecognitionbyCA::makeTracksters(
    const edm::Event &ev,
    const edm::EventSetup &es,
    const std::vector<reco::CaloCluster> &layerClusters,
    const std::vector<std::pair<unsigned int, float>> &mask, std::vector<Trackster> &result)
{
    rhtools_.getEventSetup(es);

    clearHistogram();
    theGraph_.clear();
    std::cout << "making Tracksters with CA" << std::endl;
    std::vector<HGCDoublet::HGCntuplet> foundNtuplets;
    fillHistogram(layerClusters, mask);
    theGraph_.makeAndConnectDoublets(histogram_, nEtaBins_, nPhiBins_, layerClusters, 2, 2, 0.98);
    theGraph_.findNtuplets(foundNtuplets, 4);
//#ifdef FP_DEBUG
    const auto &doublets = theGraph_.getAllDoublets();
    int tracksterId = 0;
    for (auto &ntuplet : foundNtuplets)
    {
        std::set<unsigned int> effective_cluster_idx;
        for (auto &doublet : ntuplet)
        {
            auto innerCluster = doublets[doublet].getInnerClusterId();
            auto outerCluster = doublets[doublet].getOuterClusterId();
            effective_cluster_idx.insert(innerCluster);
            effective_cluster_idx.insert(outerCluster);
            std::cout << "new doublet " << doublet <<std::endl;
            std::cout << innerCluster
                      << " " << layerClusters[innerCluster].x()
                      << " " << layerClusters[innerCluster].y()
                      << " " << layerClusters[innerCluster].z()
                      << " " << std::endl;
            std::cout << outerCluster
                      << " " << layerClusters[outerCluster].x()
                      << " " << layerClusters[outerCluster].y()
                      << " " << layerClusters[outerCluster].z()
                      << " " << tracksterId << std::endl;
        }
        // Put back indices, in the form of a Trackster, into the results vector
        Trackster tmp;
        tmp.vertices.reserve(effective_cluster_idx.size());
        std::copy(std::begin(effective_cluster_idx),
                  std::end(effective_cluster_idx),
                  std::back_inserter(tmp.vertices));
        result.push_back(tmp);
        tracksterId++;
    }
//#endif
}
