#ifndef __L1Trigger_L1THGCal_HGCalStage1TruncationImpl_h__
#define __L1Trigger_L1THGCal_HGCalStage1TruncationImpl_h__

#include "FWCore/ParameterSet/interface/ParameterSet.h" // NEED TO GET RID OF DEPENDANCE
#include "L1Trigger/L1THGCal/interface/backend/HGCalTriggerCell_SA.h"
#include "L1Trigger/L1THGCal/interface/backend/HGCalStage1TruncationConfig_SA.h"

#include <vector>

class HGCalStage1TruncationImplSA {
public:
  HGCalStage1TruncationImplSA();
  ~HGCalStage1TruncationImplSA() {}

  void runAlgorithm() const;

  l1thgcfirmware::HGCalTriggerCellSACollection run(const l1thgcfirmware::HGCalTriggerCellSACollection& tcs_in,
                                                   const l1thgcfirmware::Stage1TruncationConfig theConf) const;

private:

  static constexpr unsigned offset_roz_ = 1;
  static constexpr unsigned mask_roz_ = 0x3f;  // 6 bits, max 64 bins
  static constexpr unsigned mask_phi_ = 1;

  bool do_truncate_;
  double roz_min_ = 0.;
  double roz_max_ = 0.;
  unsigned roz_bins_ = 42;
  std::vector<unsigned> max_tcs_per_bin_;
  std::vector<double> phi_edges_;

  uint32_t packBin(unsigned roverzbin, unsigned phibin) const;
  void unpackBin(unsigned packedbin, unsigned& roverzbin, unsigned& phibin) const;
  unsigned phiBin(unsigned roverzbin, double phi, std::vector<double> phiedges) const;
  double rotatedphi(double x, double y, double z, int sector) const;
};

#endif
