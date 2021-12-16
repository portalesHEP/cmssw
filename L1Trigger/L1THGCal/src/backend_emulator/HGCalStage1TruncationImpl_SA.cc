#include "L1Trigger/L1THGCal/interface/backend_emulator/HGCalStage1TruncationImpl_SA.h"
#include <cmath>
#include <iostream>

using namespace l1thgcfirmware;

HGCalStage1TruncationImplSA::HGCalStage1TruncationImplSA() {}

unsigned HGCalStage1TruncationImplSA::run(const l1thgcfirmware::HGCalTriggerCellSACollection& tcs_in,
                                          const l1thgcfirmware::Stage1TruncationConfig& theConf,
                                          l1thgcfirmware::HGCalTriggerCellSACollection& tcs_out) const {
  std::cout << "entering run" << std::endl;
  //unsigned sector120 = theConf.phiSector();
  std::unordered_map<unsigned, std::vector<l1thgcfirmware::HGCalTriggerCell>> tcs_per_bin;

  // configuation:
  bool do_truncate = theConf.doTruncate();
  double rozmin = theConf.rozMin() /** 4096/ 0.7*/; // "magic numbers" needed for s1 input format
  double rozmax = theConf.rozMax() /** 4096/ 0.7*/; // "magic numbers" needed for s1 input format
  unsigned rozbins = theConf.rozBins();
  const std::vector<unsigned>& maxtcsperbin = theConf.maxTcsPerBin();
  const std::vector<double>& phiedges = theConf.phiEdges();

  constexpr double margin = 1.001;
  double roz_bin_size = (rozbins > 0 ? (rozmax - rozmin) * margin / double(rozbins) : 0.);

  // group TCs per (r/z, phi) bins
  for (const auto& tc : tcs_in) {
    double roverz = tc.rOverZ() / 10000.; // undo magic number
    roverz = (roverz < rozmin ? rozmin : roverz);
    roverz = (roverz > rozmax ? rozmax : roverz);

    unsigned roverzbin = (roz_bin_size > 0. ? unsigned((roverz - rozmin) / roz_bin_size) : 0);
    double phi = tc.phi()/10000.;//rotatedphi(tc.phi()/10000., sector120); // needed?
    int phibin = phiBin(roverzbin, phi, phiedges);
    if (phibin < 0)
      return 1;
    //unsigned packed_bin = packBin(roverzbin, phibin);
    uint32_t packed_bin = packBin(roverzbin, phibin);

    if (tcs_per_bin.find(packed_bin) == tcs_per_bin.end() ) {
      tcs_per_bin[packed_bin] = std::vector<l1thgcfirmware::HGCalTriggerCell>{tc};
      tcs_per_bin[packed_bin].push_back(tc);
      std::cout << "=> temp tcs_per_bin["<<packed_bin<<"].size()="<<tcs_per_bin[packed_bin].size()
            << "=> temp tcs_per_bin["<<packed_bin<<"].capacity()="<<tcs_per_bin[packed_bin].capacity()<< " (just created)"<<std::endl;
    } else {
      tcs_per_bin[packed_bin].reserve(tcs_per_bin[packed_bin].size()+1);
      std::cout <<"bin="<<packed_bin<<std::endl;
      tcs_per_bin[packed_bin].push_back(tc);
      std::cout << "=> temp tcs_per_bin["<<packed_bin<<"].size()="<<tcs_per_bin[packed_bin].size()
            << "=> temp tcs_per_bin["<<packed_bin<<"].capacity()="<<tcs_per_bin[packed_bin].capacity()<< " (just created)"<<std::endl;
    }
  }
  std::cout << "reaching truncation loop" << std::endl;
  // sorting and truncation (Batcher mergesort)
  for (auto& bin_tcs : tcs_per_bin) {
    unsigned a=0;
    unsigned b=0;
    unsigned bin_hash = bin_tcs.first;
    unpackBin(bin_hash, a,b);
//    l1thgcfirmware::HGCalTriggerCellSACollection thevec = bin_tcs.second; // throws BadAlloc
    std::cout << "tcs_per_bin["<<bin_hash<<"](["<<a<<"]["<<b<<"]).size()="<<bin_tcs.second.size()<<std::endl;
  }

  for (auto& bin_tcs : tcs_per_bin) {

    unsigned roverzbin = 0;
    unsigned phibin = 0;
    std::cout << "unpacking bin" << std::endl;
    unpackBin(bin_tcs.first, roverzbin, phibin);

    std::cout << "defining ntcin/ntcout" << std::endl;
    const unsigned ntcin = smallerMultOfFourGreaterThan(bin_tcs.second.size());
    const unsigned ntcout = (do_truncate ? maxtcsperbin[roverzbin] : bin_tcs.second.size());
    std::cout << "=> ntcin = " << ntcin << " | ntcout = " << ntcout << " (bin_tcs.second.size()=" << bin_tcs.second.size()<<std::endl;

    std::cout << "defining sorter" << std::endl;
    l1thgcfirmware::HGCalStage1SortingAlg_SA tcSorter(ntcin,ntcout);

    std::cout << "defining sorter input/outputs" << std::endl;
    std::vector<unsigned> theTCsIn_mipt(ntcin);
    std::vector<unsigned> theTCsOut_mipt(ntcout);
    std::vector<unsigned> theTCsOut_addr(ntcout);

    std::cout << "filling sorter input vector (zero-padding if needed)" << std::endl;
    for (unsigned i=0; i<ntcin; ++i) {
      if(i<bin_tcs.second.size())
        theTCsIn_mipt[i] = bin_tcs.second.at(i).energy();
      else
        theTCsIn_mipt[i] = 0;
    }
    std::cout << "apply sorter" << std::endl;
    tcSorter.sorting(theTCsIn_mipt, theTCsOut_mipt, theTCsOut_addr);

    std::cout << "fill method output" << std::endl;
    for (const unsigned& tcid : theTCsOut_addr) {
      if(tcid<bin_tcs.second.size())
        tcs_out.push_back(bin_tcs.second.at(tcid));
    }
  }

  return 0;
}

unsigned HGCalStage1TruncationImplSA::packBin(unsigned roverzbin, unsigned phibin) const {
  unsigned packed_bin = 0;
  packed_bin |= ((roverzbin & mask_roz_) << offset_roz_);
  packed_bin |= (phibin & mask_phi_);
  return packed_bin;
}

void HGCalStage1TruncationImplSA::unpackBin(unsigned packedbin, unsigned& roverzbin, unsigned& phibin) const {
  roverzbin = ((packedbin >> offset_roz_) & mask_roz_);
  phibin = (packedbin & mask_phi_);
}

int HGCalStage1TruncationImplSA::phiBin(unsigned roverzbin, double phi, const std::vector<double>& phiedges) const {
  unsigned phi_bin = 0;
  if (roverzbin >= phiedges.size())
    return -1;
  double phi_edge = phiedges[roverzbin];
  if (phi > phi_edge)
    phi_bin = 1;
  return phi_bin;
}

double HGCalStage1TruncationImplSA::rotatedphi(double phi, unsigned sector) const {
  if (sector == 1) {
    if (phi < M_PI and phi > 0)
      phi = phi - (2. * M_PI / 3.);
    else
      phi = phi + (4. * M_PI / 3.);
  } else if (sector == 2) {
    phi = phi + (2. * M_PI / 3.);
  }
  return phi;
}

unsigned HGCalStage1TruncationImplSA::smallerMultOfFourGreaterThan(unsigned N) const {
  unsigned remnant = (N+4)%4;
  if (remnant==0)
    return N;
  else
    return (N+4-remnant);
}
