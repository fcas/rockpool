## __init__.py Smart importer for submodules
import importlib
from warnings import warn

# - Dictionary {module file} -> {class name to import}
dModules = {
    ".layer": "Layer",
    ".internal.iaf_brian": (
        "FFIAFBrian",
        "FFIAFSpkInBrian",
        "RecIAFBrian",
        "RecIAFSpkInBrian",
    ),
    ".internal.rate": ("FFRateEuler", "PassThrough", "RecRateEuler"),
    ".internal.dynap_hw": (
        "RecDynapSE",
    ),
    ".internal.event_pass": "PassThroughEvents",
    ".internal.exp_synapses_brian": "FFExpSynBrian",
    ".internal.exp_synapses_manual": "FFExpSyn",
    ".internal.evSpikeLayer": "EventDrivenSpikingLayer",
    ".internal.iaf_cl": ("FFCLIAF", "RecCLIAF", "CLIAF"),
    ".internal.iaf_cl_extd": "RecCLIAFExtd",
    ".internal.softmaxlayer": "SoftMaxLayer",
    ".internal.averagepooling": "AveragePooling2D",
    ".internal.iaf_digital": "RecDIAF",
    ".internal.spike_bt": "RecFSSpikeEulerBT",
    ".internal.cnnweights": "CNNWeight",
    ".internal.spiking_conv2d_torch": "CNNWeightTorch",
    ".internal.torch_cnn_layer": "FFCLIAFTorch",
    ".internal.updown": "FFUpDown",
    ".internal.weights": (
        "RndmSparseEINet",
        "RandomEINet",
        "WilsonCowanNet",
        "WipeNonSwitchingEigs",
        "UnitLambdaNet",
        "DiscretiseWeightMatrix",
        "DynapseConform",
        "In_Res_Dynapse",
        "digital",
        "in_res_digital",
        "IAFSparseNet",
        "combine_FF_Rec_stack",
        "one_dim_exc_res",
        "two_dim_exc_res",
        "add_random_long_range",
        "partitioned_2d_reservoir",
    ),
    ".internal.pytorch.iaf_conv2d": "TorchSpikingConv2dLayer",
    ".internal.pytorch.sumpool2d": "TorchSumPooling2dLayer",
    ".internal.pytorch.crop2d": "TorchCropping2dLayer",
    ".internal.pytorch.iaf_torch": (
        "FFIAFTorch",
        "FFIAFSpkInTorch",
        "RecIAFTorch",
        "RecIAFSpkInTorch",
    ),
    # ".internal.pytorch.exp_synapses_torch": "FFExpSynTorch",
}


# - Define current package
strBasePackage = "NetworksPython.layers"

# - Initialise list of available modules
__all__ = []

# - Loop over submodules to attempt import
for strModule, classnames in dModules.items():
    try:
        if isinstance(classnames, str):
            # - Attempt to import the module, get the requested class
            strClass = classnames
            locals()[strClass] = getattr(
                importlib.import_module(strModule, strBasePackage), strClass
            )

            # - Add the resulting class to __all__
            __all__.append(strClass)

        elif isinstance(classnames, tuple):
            for strClass in classnames:
                # - Attempt to import the module
                locals()[strClass] = getattr(
                    importlib.import_module(strModule, strBasePackage), strClass
                )

                # - Add the resulting class to __all__
                __all__.append(strClass)

        elif classnames is None:
            # - Attempt to import the module alone
            locals()[strModule] = importlib.import_module(strModule, strBasePackage)

            # - Add the module to __all__
            __all__.append(strModule)

    except ModuleNotFoundError as err:
        # - Ignore ModuleNotFoundError
        warn("Could not load package " + strModule)
        print(err)
        pass

    except ImportError as err:
        # - Raise a warning if the package could not be imported for any other reason
        warn("Could not load package " + strModule)
        print(err)


# from .internal import *

# from .internal import __all__ as suball

# __all__ += suball
