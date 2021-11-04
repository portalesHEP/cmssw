#include "FWCore/ParameterSet/interface/ParameterSet.h"

#include "L1Trigger/L1THGCal/interface/HGCalAlgoWrapperBase.h"

#include "DataFormats/L1THGCal/interface/HGCalTriggerCell.h"
#include "L1Trigger/L1THGCal/interface/backend/HGCalTriggerCell_SA.h"
#include "L1Trigger/L1THGCal/interface/backend/HGCalStage1TruncationImpl_SA.h"
#include "L1Trigger/L1THGCal/interface/backend/HGCalStage1TruncationConfig_SA.h"

#include "FWCore/MessageLogger/interface/MessageLogger.h"

#include "L1Trigger/L1THGCal/interface/HGCalTriggerGeometryBase.h"
#include "L1Trigger/L1THGCal/interface/HGCalTriggerTools.h"

#include "DataFormats/GeometryVector/interface/GlobalPoint.h"
#include "DataFormats/L1Trigger/interface/L1Candidate.h"
#include "DataFormats/L1Trigger/interface/BXVector.h"
#include "DataFormats/DetId/interface/DetId.h"

class HGCalStage1TruncationWrapper : public HGCalStage1TruncationWrapperBase {
public:
  HGCalStage1TruncationWrapper(const edm::ParameterSet& conf);
  ~HGCalStage1TruncationWrapper() override {}

  void configure(const std::pair<const edm::EventSetup&, const edm::ParameterSet&>& configuration) override;

  void process(const std::pair<std::pair<uint32_t,unsigned>,std::vector<edm::Ptr<l1t::HGCalTriggerCell>>>& fpga_id_tcs,
               std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& tcs_out) const override;

private:
  void convertCMSSWInputs(const std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& fpga_tcs,
                          l1thgcfirmware::HGCalTriggerCellSACollection& fpga_tcs_SA) const;

  void convertAlgorithmOutputs(const l1thgcfirmware::HGCalTriggerCellSACollection& fpga_tcs_out,
                               const std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& fpga_tcs_original,
                               std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& fpga_tcs_trunc) const;

  void eventSetup(const edm::EventSetup& es) { triggerTools_.eventSetup(es); }

  HGCalTriggerTools triggerTools_;
  HGCalStage1TruncationImplSA theAlgo_;
  l1thgcfirmware::Stage1TruncationConfig theConfiguration_;
};

HGCalStage1TruncationWrapper::HGCalStage1TruncationWrapper(const edm::ParameterSet& conf)
    : HGCalStage1TruncationWrapperBase(conf),
      theAlgo_(),
      theConfiguration_(conf.getParameter<bool>("doTruncation"),
                        conf.getParameter<double>("rozMin"),
                        conf.getParameter<double>("rozMax"),
                        conf.getParameter<unsigned>("rozBins"),
                        conf.getParameter<std::vector<unsigned>>("maxTcsPerBin"),
                        conf.getParameter<std::vector<double>>("phiSectorEdges")) {}


void HGCalStage1TruncationWrapper::convertCMSSWInputs(const std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& fpga_tcs,
                        l1thgcfirmware::HGCalTriggerCellSACollection& fpga_tcs_SA) const {
  fpga_tcs_SA.clear();
  fpga_tcs_SA.reserve(fpga_tcs.size());
  unsigned int itc = 0;
  for (auto& tc: fpga_tcs) {
    fpga_tcs_SA.emplace_back(tc->position().x(),
                             tc->position().y(),
                             tc->position().z(),
                             triggerTools_.zside(tc->detId()),
                             triggerTools_.layerWithOffset(tc->detId()),
                             tc->eta(),
                             tc->phi(),
                             tc->pt(),
                             tc->mipPt(),
                             itc);
    ++itc;
  }
}

void HGCalStage1TruncationWrapper::convertAlgorithmOutputs(const l1thgcfirmware::HGCalTriggerCellSACollection& fpga_tcs_out,
                                                           const std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& fpga_tcs_original,
                                                           std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& fpga_tcs_trunc) const {
  for(unsigned itc = 0; itc < fpga_tcs_out.size(); ++itc){
    unsigned tc_cmssw_id = fpga_tcs_out[itc].index_cmssw();
    fpga_tcs_trunc.push_back(fpga_tcs_original[tc_cmssw_id]);
  }
}

void HGCalStage1TruncationWrapper::process(
              const std::pair<std::pair<uint32_t,unsigned>,std::vector<edm::Ptr<l1t::HGCalTriggerCell>>>& fpga_id_tcs,
              std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& tcs_out) const {

  l1thgcfirmware::HGCalTriggerCellSACollection fpga_tcs_SA;
  convertCMSSWInputs(fpga_id_tcs.second, fpga_tcs_SA);

  l1thgcfirmware::HGCalTriggerCellSACollection tcs_out_SA = theAlgo_.run(fpga_id_tcs.first, fpga_tcs_SA, theConfiguration_);

  convertAlgorithmOutputs(tcs_out_SA, fpga_id_tcs.second, tcs_out);
}

void HGCalStage1TruncationWrapper::configure(const std::pair<const edm::EventSetup&,
                                             const edm::ParameterSet&>& configuration) {
  eventSetup(configuration.first);
};

DEFINE_EDM_PLUGIN(HGCalStage1TruncationWrapperBaseFactory,
                  HGCalStage1TruncationWrapper,
                  "HGCalStage1TruncationWrapper");
