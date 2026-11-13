import tsgauth
import argparse
import os
import re
import sys
import difflib
import requests
import time
from urllib.parse import urlencode

DEFAULT_SOURCE = "offline-run3"


# ---------------------------------------------------------------------------
# --cff support
#
# hltGetConfiguration --cff does two things (HLTrigger/Configuration/python/Tools/confdb.py):
#   1. it asks the ConfDB converter to leave out a fixed list of ESSources, ESModules,
#      services, PSets and output EndPaths (HLTProcess.buildOptions / buildPathList);
#   2. it renames process -> fragment and cms.Process -> cms.ProcessFragment (HLTProcess.dump).
# The config API has no converter options and returns a full cmsDriver job (source,
# output module, GlobalTag, geometry, event content, mixing, ...), so the same thing is
# done here on the parsed process instead.
# ---------------------------------------------------------------------------
# Usage:
# 
# (1) dump a baseline config to identify non-HLT-related processes
#
# cmsDriver.py RelVal -s L1P2GT:v0p0_2026 \
#     --processName=HLTX \
#     --conditions auto:phase2_realistic_T35 --geometry ExtendedRun4D121 --era Phase2C22I13M9 \
#     --eventcontent FEVTDEBUGHLT --mc \
#     --filein=/store/relval/CMSSW_20_0_0_pre1/RelValTTbar_14TeV/GEN-SIM-DIGI-RAW/PU_150X_mcRun4_realistic_v1_STD_D121_RegeneratedGS_PU-v1/2590000/0033230b-a131-453a-95c0-fe14d5027d1f.root \
#     -n 10 --output '{}' \
#     --inputCommands "keep *, drop *_hlt*_*_HLT, drop triggerTriggerFilterObjectWithRefs_l1t*_*_HLT" \
#     --customise SLHCUpgradeSimulations/Configuration/aging.customise_aging_1000 \
#     --no_exec --python_filename baseline_cfg.py > baseline.log 2>&1
#
# (2) dump and reformat the hlt config
#
# python3 test/hltGetConfig_NewConfdb.py \
#     gitlab:/users/lportale/Phase2_dev/CMSSX_20_1_X-HLT-V2_fix/V3 \
#     --cff \
#     --baseline baseline_cfg.py \
#     -o HLT_MYTEST_cff.py
#
# ---------------------------------------------------------------------------

# same lists as Tools/confdb.py, HLTProcess.buildOptions(), fragment case
FRAGMENT_DROP_ESSOURCES = [
    "GlobalTag", "HepPDTESSource", "XMLIdealGeometryESSource", "eegeom", "es_hardcode", "magfield",
]
FRAGMENT_DROP_ESMODULES = [
    "SlaveField0", "SlaveField20", "SlaveField30", "SlaveField35", "SlaveField38", "SlaveField40",
    "VBF0", "VBF20", "VBF30", "VBF35", "VBF38", "VBF40",
    "CSCGeometryESModule", "CaloGeometryBuilder", "CaloTowerHardcodeGeometryEP", "CastorHardcodeGeometryEP",
    "DTGeometryESModule", "EcalBarrelGeometryEP", "EcalElectronicsMappingBuilder", "EcalEndcapGeometryEP",
    "EcalLaserCorrectionService", "EcalPreshowerGeometryEP", "GEMGeometryESModule", "HcalHardcodeGeometryEP",
    "HcalTopologyIdealEP", "MuonNumberingInitialization", "ParametrizedMagneticFieldProducer",
    "RPCGeometryESModule", "SiStripGainESProducer", "SiStripRecHitMatcherESProducer",
    "SiStripQualityESProducer", "StripCPEfromTrackAngleESProducer",
    "TrackerAdditionalParametersPerDetESModule", "TrackerDigiGeometryESModule",
    "TrackerGeometricDetESModule", "VolumeBasedMagneticFieldESProducer", "ZdcHardcodeGeometryEP",
    "hcal_db_producer", "L1GtTriggerMaskAlgoTrigTrivialProducer", "L1GtTriggerMaskTechTrigTrivialProducer",
    "hltESPEcalTrigTowerConstituentsMapBuilder", "hltESPGlobalTrackingGeometryESProducer",
    "hltESPMuonDetLayerGeometryESProducer", "hltESPTrackerRecoGeometryESProducer", "trackerTopology",
    "CaloTowerGeometryFromDBEP", "CastorGeometryFromDBEP", "EcalBarrelGeometryFromDBEP",
    "EcalEndcapGeometryFromDBEP", "EcalPreshowerGeometryFromDBEP", "HcalGeometryFromDBEP",
    "ZdcGeometryFromDBEP", "XMLFromDBSource", "sistripconn", "siPixelQualityESProducer",
]
FRAGMENT_DROP_SERVICES = [
    # always dropped by hltGetConfiguration (non-hilton)
    "DQM", "FUShmDQMOutputService", "MicroStateService", "ModuleWebRegistry", "TimeProfilerService",
    "EvFDaqDirector", "FastMonitoringService", "DQMStore",
    # dropped for fragments
    "MessageLogger", "PrescaleService", "FastTimerService", "ThroughputService",
    # cmsDriver job setting, would override the seeds of the job the fragment is loaded into
    "RandomNumberGeneratorService",
]
# cmsDriver job settings, never part of a menu
FRAGMENT_DROP_PSETS = ["maxEvents", "maxLuminosityBlocks", "options", "configurationMetadata"]
# paths hltGetConfiguration never puts in a fragment
FRAGMENT_DROP_PATHS = ["RatesMonitoring", "DQMHistograms", "OfflineOutput"]

FRAGMENT_FOOTER = """
# dummify hltGetConditions in cff's
if 'hltGetConditions' in fragment.__dict__ and 'HLTriggerFirstPath' in fragment.__dict__ :
    fragment.hltDummyConditions = cms.EDFilter( "HLTBool",
        result = cms.bool( True )
    )
    fragment.HLTriggerFirstPath.replace(fragment.hltGetConditions,fragment.hltDummyConditions)
"""


def _load_process(cfg_text, filename):
    ns = {"__file__": filename, "__name__": "__cfg__"}
    exec(compile(cfg_text, filename, "exec"), ns)
    if "process" not in ns:
        raise RuntimeError(f"{filename} does not define a 'process'")
    return ns["process"]


# object categories compared against the --baseline config
BASELINE_CATEGORIES = [
    ("es_sources", "es_sources_"), ("es_producers", "es_producers_"), ("es_prefers", "es_prefers_"),
    ("services", "services_"), ("psets", "psets_"), ("vpsets", "vpsets_"), ("aliases", "aliases_"),
]

_BASELINE_DUMPER = """
import json, sys
ns = {"__file__": sys.argv[1], "__name__": "__cfg__"}
exec(compile(open(sys.argv[1]).read(), sys.argv[1], "exec"), ns)
p = ns["process"]
cats = json.loads(sys.argv[2])
json.dump({kind: {n: o.dumpPython() for n, o in getattr(p, getter)().items()} for kind, getter in cats}, sys.stdout)
"""


def _baseline_objects(baseline_file):
    # CMSSW does not allow two Processes with different era Modifiers in the same
    # interpreter, so the baseline is loaded in a separate python process
    import json, subprocess
    res = subprocess.run([sys.executable, "-c", _BASELINE_DUMPER, baseline_file, json.dumps(BASELINE_CATEGORIES)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"failed to load baseline config {baseline_file}:\n{res.stderr}")
    return json.loads(res.stdout)


def make_fragment(cfg_text, baseline_file=None, header="", verbose=False):
    """Turn the full python config returned by the API into a cff fragment
    equivalent to what hltGetConfiguration --cff produces.

    baseline_file: optional cmsDriver config of the job the fragment will be used in,
    generated *without* the HLT step. Every ESSource/ESProducer/service that is also in
    the baseline with identical parameters is dropped, since cmsDriver already provides it;
    ones with the same label but different parameters are kept (the menu overrides them,
    as with hltGetConfiguration) and reported. PSets/VPSets/EDAliases in the baseline are
    dropped by label (event content, digitizer settings, ... belong to the job, not the menu).
    """
    try:
        import FWCore.ParameterSet.Config as cms
    except ImportError:
        sys.exit("--cff needs a CMSSW environment (cmsenv) to parse the configuration")

    process = _load_process(cfg_text, "<hltcfg-api>")
    removed = {}

    def drop(kind, name):
        if hasattr(process, name):
            delattr(process, name)
            removed.setdefault(kind, []).append(name)

    # --- cmsDriver wrapper ---------------------------------------------------
    # cms.Process has no API to unset the source/looper (delattr is a no-op for them),
    # so clear the slots _placeSource/_placeLooper fill
    for attr in ("source", "looper"):
        obj = getattr(process, attr, None)
        if obj is not None:
            process.__dict__.pop(obj.type_(), None)
            process.__dict__[f"_Process__{attr}"] = None
            removed.setdefault("wrapper", []).append(attr)
    for name in FRAGMENT_DROP_PSETS:
        drop("psets", name)
    # output modules (also removes them from their EndPaths)
    for name in list(process.outputModules_()):
        drop("outputs", name)
    # cmsDriver steps (endjob_step, FEVTDEBUGHLToutput_step, ...) and paths never in fragments
    for name in list(process.paths_()) + list(process.endpaths_()):
        if name.endswith("_step") or name in FRAGMENT_DROP_PATHS:
            drop("paths", name)
    # EndPaths that only held an output module are now empty
    for name, ep in list(process.endpaths_().items()):
        if not ep.moduleNames():
            drop("paths", name)

    # --- hltGetConfiguration fragment blacklist --------------------------------
    for name in FRAGMENT_DROP_ESSOURCES:
        drop("es_sources", name)
    for name in FRAGMENT_DROP_ESMODULES:
        drop("es_producers", name)
    for name in FRAGMENT_DROP_SERVICES:
        drop("services", name)

    # --- schedule: menu order, HLTriggerFinalPath after the trigger paths, EndPaths last
    paths = [p for n, p in process.paths_().items() if n != "HLTriggerFinalPath"]
    if "HLTriggerFinalPath" in process.paths_():
        paths.append(process.HLTriggerFinalPath)
    paths += list(process.endpaths_().values())
    if hasattr(process, "finalpaths_"):
        paths += list(process.finalpaths_().values())
    if not paths:
        raise RuntimeError("no Paths left in the configuration")
    process.schedule = cms.Schedule(*paths)

    # --- drop modules / sequences / tasks not used by the menu (mix, endOfProcess, ...)
    process.prune(verbose=verbose)

    # --- drop what the cmsDriver job already provides --------------------------
    differing = []
    if baseline_file:
        baseline = _baseline_objects(baseline_file)
        for kind, getter in BASELINE_CATEGORIES:
            ours, theirs = getattr(process, getter)(), baseline[kind]
            for name in list(ours):
                if name not in theirs:
                    continue
                if kind in ("psets", "vpsets", "aliases") or ours[name].dumpPython() == theirs[name]:
                    drop(kind, name)
                else:
                    differing.append(f"{kind}:{name}")

    # EDAliases that are empty or point to modules not in the fragment (e.g. simSiPixelDigis -> mix)
    modules = set(process.producers_()) | set(process.filters_()) | set(process.analyzers_())
    if hasattr(process, "switchProducers_"):
        modules |= set(process.switchProducers_())
    for name, alias in list(process.aliases_().items()):
        targets = set(alias.parameterNames_())
        if not targets or not targets <= modules:
            drop("aliases", name)

    # --- report ----------------------------------------------------------------
    for kind, names in removed.items():
        sys.stderr.write(f"--cff: removed {len(names)} {kind}" + (f": {', '.join(sorted(names))}" if verbose else "") + "\n")
    if differing:
        sys.stderr.write(f"--cff: kept {len(differing)} objects whose label is in the baseline but whose "
                         f"parameters differ (the menu overrides them): {', '.join(differing)}\n")
    if not baseline_file:
        sys.stderr.write("--cff: no --baseline given, so standard ESProducers/PSets from the cmsDriver job "
                         "(geometry, event content, ...) are still in the fragment\n")

    # --- process -> fragment, as in HLTProcess.dump() ----------------------------
    data = process.dumpPython()
    data = re.sub(r"\bprocess\.", "fragment.", data)
    data = re.sub(r"^process = cms\.Process\(", "fragment = cms.ProcessFragment(", data, flags=re.M)
    # dumpPython() does not write out ProcessAccelerators, without them @alpaka modules cannot
    # be resolved; the menus in the release (and hltGetConfiguration) load them explicitly
    data = re.sub(r"^(fragment = cms\.ProcessFragment\(.*\)\n)",
                  r'\1\nfragment.load("Configuration.StandardSequences.Accelerators_cff")\n', data, count=1, flags=re.M)
    return header + data + FRAGMENT_FOOTER

def get_url(url,auth : tsgauth.oidcauth.AuthBase):
    request_chain = []
    request_chain.append(requests.get(url,headers=auth.headers()))
    r = request_chain[-1]
    if r.status_code==404:
       create_info = r.json().get("links",{}).get("create",None)
       if create_info is not None:          
          request_chain.append(requests.put(create_info["href"],headers=auth.headers()))
          r_create = request_chain[-1]
          if r_create.status_code != 202:
              return request_chain
          
    while request_chain[-1].status_code in [202, 204]:
        time.sleep(2)
        r = request_chain[-1]
        status_url = r.json().get("links",{}).get("status",{}).get("href",None)
        if status_url is None:
            break
        request_chain.append(requests.get(status_url,headers=auth.headers()))

    return request_chain

def print_error(response):
    try:
        response.json()
    except Exception as e:
        print(f"Error printing response: {e}")
    else:
        error_str = "Error response:\n"
        for key, value in response.json().items():
            error_str += f"{key}: {value}\n"
        print(error_str)


class HLTConfigURLs:
    def __init__(self, host):
        self.host = host
        self.apiprefix = f"{self.host}/api/test"
        
    def menu(self, source, menu):
        return f"{self.apiprefix}/sources/{source}/configs/python?cfg={menu}"

    def sources(self):
        return f"{self.apiprefix}/sources"

    def cfg_names(self, source):
        return f"{self.apiprefix}/sources/{source}/configs"

    def latest_version(self, source, series):
        # series = menu name without version, e.g. /users/me/menu/HLT (contains '/', so it must be encoded)
        return f"{self.apiprefix}/sources/{source}/configs/latest-version?{urlencode({'series': series})}"

class HLTConfigGetter:
    def __init__(self, host, auth):
        self.urls = HLTConfigURLs(host)
        self.auth = auth
        self.verbose_level = 0

    @staticmethod
    def split_menu(menupath):
        if ":" not in menupath:
            return DEFAULT_SOURCE, menupath
        else:
            return menupath.split(":",1)

    @staticmethod
    def auto_filename_root(menupath):
        source, menu = HLTConfigGetter.split_menu(menupath)
        source = source.replace("/", "_")
        menu = menu.replace("/", "_")
        return f"{source}_{menu}"

    def get(self, menupath):
        source, menu = self.split_menu(menupath)

        url = self.urls.menu(source, menu)        
        response_chain = get_url(url,self.auth)
        if response_chain[-1].status_code == 404:
            self.debug_missing_cfg(source, menu)
            return None
        elif response_chain[-1].status_code != 200:
            print_error(response_chain[-1])
            return None
        else:
            try:
                return response_chain[-1].json()["data"]["cfg"]
            except Exception as e:
                print(f"Error parsing response JSON: {e}, text is {response_chain[-1].text}")
                return None

    # menu names end with /V<n>; without it, a name refers to a whole series of versions
    VERSION_RE = re.compile(r"/V\d+$")

    def resolve_version(self, source, menu):
        """Return the menu name with an explicit version: unchanged if it has one, else the latest version
        of the series (or None, after printing why, if the series does not exist)."""
        if self.VERSION_RE.search(menu):
            return menu
        # the service answers {"data": <latest version number>}
        request_chain = get_url(self.urls.latest_version(source, menu), self.auth)
        if request_chain[-1].status_code == 200:
            try:
                version = request_chain[-1].json().get("data")
            except Exception:
                version = None
            if isinstance(version, int) and not isinstance(version, bool):
                resolved = f"{menu}/V{version}"
                sys.stderr.write(f"no version given, using the latest one: {source}:{resolved}\n")
                return resolved
        # fallback: the menu listing, {series: [full names sorted by version]}
        series = self.get_cfg_names(source)
        if series and series.get(menu):
            resolved = series[menu][-1]
            sys.stderr.write(f"no version given, using the latest one: {source}:{resolved}\n")
            return resolved
        self.debug_missing_cfg(source, menu)
        return None

    def get_sources(self):
        """List of source names, or None if the list could not be retrieved."""
        request_chain = get_url(self.urls.sources(), self.auth)
        if request_chain[-1].status_code != 200:
            print_error(request_chain[-1])
            return None
        data = request_chain[-1].json().get("data") or {}
        # the service answers {"data": {"names": [...]}}
        return data.get("names", []) if isinstance(data, dict) else list(data)

    def debug_missing_cfg(self, source, menu):
        """Explain why source:menu was not found."""
        sources = self.get_sources()
        if sources is None:
            print("could not retrieve the list of sources (see the error above)")
            return None
        if source not in sources:
            print(f"Source '{source}' not found. Valid sources: {', '.join(sources)}")
            return None
        series = self.get_cfg_names(source)
        if series is None:
            print(f"could not retrieve the menus in source '{source}' (see the error above)")
            return None
        parent = menu.rsplit("/", 1)[0]
        if menu in series:
            # a series name without version
            versions = ", ".join(name.rsplit("/", 1)[1] for name in series[menu])
            print(f"'{menu}' is a menu without version: add one of {versions} (latest: {series[menu][-1]})")
        elif self.VERSION_RE.search(menu) and parent in series:
            # known series, unknown version
            print(f"'{menu}' not found. Available versions: {', '.join(series[parent])}")
        else:
            close = difflib.get_close_matches(menu, list(series), n=5, cutoff=0.6)
            hint = f". Did you mean: {', '.join(close)}" if close else f" ({len(series)} menus in this source)"
            print(f"Menu '{menu}' not found in source '{source}'{hint}")
        return None

    def get_cfg_names(self, source):
        """{series name: [full config names sorted by version]}, or None if the list could not be retrieved."""
        request_chain = get_url(self.urls.cfg_names(source), self.auth)
        if request_chain[-1].status_code != 200:
            print_error(request_chain[-1])
            return None
        data = request_chain[-1].json().get("data") or {}
        # the service answers {"data": {series: [ConfigInfo{name, series_name, version, ...}, ...]}}
        return {series: [c["name"] for c in sorted(cfgs, key=lambda c: c.get("version") or 0)]
                for series, cfgs in data.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get HLT configuration")
    parser.add_argument("menupath", nargs="?", default=None,
                        help="menu name with format source:menu; if no version is specified (/V<n> at the end) "
                             "the latest version of the menu is used")
    parser.add_argument("--host",default="https://cmshltcfg-api.app.cern.ch", help="Host of the HLT configuration service")
    parser.add_argument("--output","-o", default=None,
                        help="Output file to save the configuration. A bare file name (no directory) is written to "
                             "$CMSSW_BASE/src/HLTrigger/Configuration/python, e.g. -o HLT_MYTEST_cff.py for HLT:MYTEST; "
                             "use ./name to write to the current directory")
    parser.add_argument("--from-file", default=None, metavar="PY",
                        help="Use a python config already downloaded from the service instead of fetching menupath "
                             "(useful with --cff to convert an existing dump)")
    parser.add_argument("--cff", "--fragment", dest="fragment", action="store_true",
                        help="Generate a configuration fragment (fragment = cms.ProcessFragment) for inclusion by "
                             "e.g. cmsDriver.py -s HLT:<name>, with no input or output sections. Needs cmsenv.")
    parser.add_argument("--baseline", default=None, metavar="CFG",
                        help="With --cff: a cmsDriver config of the job the fragment will be used in, generated "
                             "without the HLT step (--no_exec) but with the same era/geometry/conditions and the same "
                             "non-HLT --customise (e.g. aging). Objects it already provides are removed from the fragment.")
    parser.add_argument("--verbose", "-v", action="store_true", help="With --cff: list everything that is removed")

    args = parser.parse_args()
    if args.baseline and not args.fragment:
        parser.error("--baseline only makes sense with --cff")
    if args.baseline and not os.path.isfile(args.baseline):
        parser.error(f"baseline config '{args.baseline}' not found (relative paths are resolved from {os.getcwd()})")
    if args.from_file:
        if not args.output and not args.menupath:
            parser.error("with --from-file, give --output (or a menupath to name the output after)")
    elif not args.menupath:
        parser.error("menupath is required unless --from-file is given")

    menupath = args.menupath
    if args.from_file:
        with open(args.from_file) as f:
            config = f.read()
    else:
        auth = tsgauth.oidcauth.DeviceAuth("cms-tsg-frontend-client")
        getter = HLTConfigGetter(args.host, auth)
        # no version given (no trailing /V<n>): use the latest one
        source, menu = HLTConfigGetter.split_menu(menupath)
        menu = getter.resolve_version(source, menu)
        if menu is None:
            sys.exit(1)
        menupath = f"{source}:{menu}"
        config = getter.get(menupath)
        if config is None:
            sys.exit(1)

    if args.fragment:
        header = f"# {' '.join([os.path.basename(sys.argv[0])] + sys.argv[1:])}\n"
        if menupath and menupath != args.menupath:
            header += f"# menu: {menupath}\n"     # record the version actually used
        config = make_fragment(config, baseline_file=args.baseline, header=header + "\n", verbose=args.verbose)

    output = args.output
    if not output:
        output = HLTConfigGetter.auto_filename_root(menupath) + ("_cff.py" if args.fragment else ".py")
    # menus live in HLTrigger/Configuration/python (where cmsDriver.py -s HLT:<name> finds them),
    # so a bare file name goes there; an explicit path is used as given
    if not os.path.dirname(output) and os.environ.get("CMSSW_BASE"):
        output = os.path.join(os.environ["CMSSW_BASE"], "src", "HLTrigger", "Configuration", "python", output)

    with open(output, "w") as f:
        f.write(config)
    sys.stderr.write(f"written {output}\n")
