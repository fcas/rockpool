## __init__.py Smart importer for submodules
import importlib
from warnings import warn

# - Dictionary {module file} -> {class name to import}
dModules = {
    ".module": "Module",
    ".timed_module": ("TimedModule", "TimedModuleWrapper"),
    ".jax.jax_module": "JaxModule",
    ".jax.lif_jax": "LIFJax",
    ".jax.rate_jax": "RateEulerJax",
    ".jax.exp_smooth_jax": "ExpSmoothJax",
    ".jax.softmax_jax": ("SoftmaxJax", "LogSoftmaxJax"),
    ".native.linear": ("Linear", "LinearJax"),
    ".native.instant": ("Instant", "InstantJax"),
    ".native.filter_bank": ("ButterMelFilter", "ButterFilter"),
    ".nest.iaf_nest": ("FFIAFNest", "RecIAFSpkInNest", "RecAEIFSpkInNest"),
    ".torch.torch_module": "TorchModule",
    ".torch.lif_torch": "LIFLayer",
}


# - Define current package
strBasePackage = "rockpool.nn.modules"

# - Define docstring for module
__doc__ = """Defines classes for simulating layers of neurons"""

# - Initialise list of available modules
__all__ = []


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


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

        elif isinstance(classnames, (tuple, list)):
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
        print(bcolors.FAIL + bcolors.BOLD + str(err) + bcolors.ENDC)
        pass

    except ImportError as err:
        # - Raise a warning if the package could not be imported for any other reason
        warn("Could not load package " + strModule)
        print(bcolors.FAIL + bcolors.BOLD + str(err) + bcolors.ENDC)
