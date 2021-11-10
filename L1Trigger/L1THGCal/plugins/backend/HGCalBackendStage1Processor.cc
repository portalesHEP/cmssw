#include "L1Trigger/L1THGCal/interface/backend/HGCalBackendStage1Processor.h"
#include "DataFormats/ForwardDetId/interface/HGCalTriggerBackendDetId.h"

DEFINE_EDM_PLUGIN(HGCalBackendStage1Factory, HGCalBackendStage1Processor, "HGCalBackendStage1Processor");

HGCalBackendStage1Processor::HGCalBackendStage1Processor(const edm::ParameterSet& conf)
    : HGCalBackendStage1ProcessorBase(conf), conf_(conf) {

  const edm::ParameterSet& truncationParamConfig = conf.getParameterSet("truncation_parameters");
  const std::string& truncationWrapperName = truncationParamConfig.getParameter<std::string>("AlgoName");

  truncationWrapper_ = std::unique_ptr<HGCalStage1TruncationWrapperBase>{
        HGCalStage1TruncationWrapperBaseFactory::get()->create(truncationWrapperName, truncationParamConfig)};

}

void HGCalBackendStage1Processor::run(
  const std::pair<uint32_t,std::vector<edm::Ptr<l1t::HGCalTriggerCell>>>& fpga_id_tcs,
  std::vector<edm::Ptr<l1t::HGCalTriggerCell>>& truncated_tcs,
  const edm::EventSetup& es) {

  // Configuration
  const std::pair<const edm::EventSetup&, const edm::ParameterSet&> configuration{es, conf_};
  truncationWrapper_->configure(configuration);

  unsigned sector120 = HGCalTriggerBackendDetId(fpga_id_tcs.first).sector();

  std::pair<uint32_t,unsigned> id_sector(fpga_id_tcs.first,sector120);
  const std::pair<std::pair<uint32_t,unsigned>,
                  std::vector<edm::Ptr<l1t::HGCalTriggerCell>>> fpga_id_sector_tcs(id_sector,fpga_id_tcs.second);

  truncationWrapper_->process(fpga_id_sector_tcs, truncated_tcs);
}
