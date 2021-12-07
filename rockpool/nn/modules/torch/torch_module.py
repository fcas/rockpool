"""
Provide a base class for build Torch-compatible modules
"""
from importlib import util

if util.find_spec("torch") is None:
    raise ModuleNotFoundError(
        "'Torch' backend not found. Modules that rely on Torch will not be available."
    )


from rockpool.nn.modules.module import Module

import torch
from torch import nn

import numpy as np
import json
import types

import rockpool.parameters as rp

from typing import Tuple, Any, Generator, Union, List

__all__ = ["TorchModule", "TorchModuleParameters"]


class TorchModuleParameters(dict):
    """
    A ``dict`` subclass that supports conversion to raw values

    Use the :py:meth:`.astorch` method to extract raw torch parameters. This is equivalent to having called :py:meth:`.Torch.nn.Module.parameters`.
    """

    def astorch(self) -> Generator[Any, None, None]:
        """
        Convert this parameter dictionary into a generator of raw torch parameters

        Yields: `Torch.nn.Parameter`
        """

        def yield_leaves(d: dict) -> Generator[Any, None, None]:
            # - Loop over values in the dictionary
            for val in d.values():
                if isinstance(val, dict):
                    # - Recurse over the dictionary
                    yield from yield_leaves(val)
                else:
                    # - Yield this leaf
                    yield val

        # - Yield leaves over self
        yield from yield_leaves(self)


class TorchModule(Module, nn.Module):
    """
    Base class for modules that are compatible with both Torch and Rockpool

    Use this base class to build Rockpool modules that use Torch as a backend. You can also use this class to convert a ``torch.nn.module`` to a Rockpool :py:class:`.Module` in one line.

    See Also:
        See :ref:`/in-depth/torch-api.ipynb` for details of using the Torch API.

    To implement a module from scratch using the Torch low-level API, simply inherit from :py:class:`.TorchModule` instead of ``torch.nn.Module``. You must implement the Torch API in the form of :py:meth:`.forward` etc. :py:class:`.TorchModule` will convert the API for you, and provides its own :py:meth:`.evolve` method. You should not implement the :py:meth:`.evolve` method yourself.

    In your :py:meth:`.forward` method you should use the Torch API and semantics as usual. Sub-modules of a Rockpool :py:class:`.TorchModule` are expected to be Torch ``nn.Module`` s. Only the top-level module needs to be wrapped as a Rockpool :py:class:`.TorchModule`.

    :py:class:`.TorchModule` automatically converts Torch parameters to Rockpool :py:class:`.Parameter` s, and Torch named buffers to Rockpool :py:class:`.State` s. In this way calls to :py:meth:`.parameters` and :py:meth:`.state` function as expected.

    Examples:

        Convert a ``torch`` module to a Rockpool :py:class:`.TorchModule`:

        >>> mod = TorchModule.from_torch(torch_mod)

    """

    def __init__(self, retain_torch_api: bool = False, *args, **kwargs):
        """
        Initialise this module

        You must override this method to initialise your module.

        Args:
            *args:
            **kwargs:
        """
        # - Ensure super-class initialisation ocurs
        super().__init__(*args, **kwargs)

        if retain_torch_api:
            self.to_torch()
            #
            # def parameters(self, *args, **kwargs):
            #     return nn.Module.parameters(self, *args, **kwargs)
            #
            # self.parameters = types.MethodType(parameters, self)
            #
            # def call(self, *args, **kwargs):
            #     return nn.Module.__call__(self, *args, **kwargs)
            #
            # self._call = types.MethodType(call, self)

    def __call__(self, *args, **kwargs):
        if hasattr(self, "_call"):
            return self._call(*args, **kwargs)
        else:
            return super().__call__(*args, **kwargs)

    def __repr__(self, *args, **kwargs):
        if hasattr(self, "_repr"):
            return self._repr(*args, **kwargs)
        else:
            return super().__repr__(*args, **kwargs)

    def evolve(self, input_data, record: bool = False) -> Tuple[Any, Any, Any]:
        """
        Implement the Rockpool low-level evolution API

        :py:meth:`.evolve` is provided by :py:class:`.TorchModule` to connect the Rockpool low-level API to the Torch API (i.e. :py:meth:`.forward` etc.). You should *not* override :py:meth:`.evolve` if using :py:class:`.TorchModule` directly, but should implement the Torch API to perform evaluation of the module.

        Args:
            input_data: This might be a numpy array or Torch tensor, containing the input data to evolve over
            record (bool): Iff ``True``, return a dictionary of state variables as ``record_dict``, containing the time series of those state variables over evolution. Default: ``False``, do not record state during evolution

        Returns:
            (array, dict, dict): (output_data, new_states, record_dict)
                ``output_data`` is the output from the :py:class:`.TorchModule`, probably as a torch ``Tensor``.
                ``new_states`` is a dictionary containing the updated state for this module, post evolution.
                If the ``record`` argument is ``True``, ``record_dict`` is a dictionary containing the recorded state variables for this and all submodules, recorded over evolution.
        """

        # - Call nn.Module.__call__() method to get output data
        output_data = nn.Module.__call__(self, input_data)

        # - Build a new state dictionary
        new_states = self.state()

        # - No general solution as yet to access recorded states
        record_dict = {}

        return output_data, new_states, record_dict

    def __setattr__(self, key, value):
        if isinstance(value, nn.Parameter):
            # - Also register as a rockpool parameter
            self._register_attribute(key, rp.Parameter(value, None, None, value.shape))

        if isinstance(value, rp.Parameter):
            # - Register as a torch parameter
            super().register_parameter(key, nn.Parameter(value.data))

            # - Register as a Rockpool attribute
            self._register_attribute(key, value)
            return

        if isinstance(value, rp.State):
            # - register as a torch buffer
            super().register_buffer(key, value.data)

            # - Register as a Rockpool attribute
            self._register_attribute(key, value)
            return

        if isinstance(value, nn.Module) and not isinstance(value, TorchModule):
            # - Convert torch module to a Rockpool Module and assign
            TorchModule.from_torch(value, retain_torch_api=True)
            self._register_module(key, value)

        # Assign attribute with setattr
        super().__setattr__(key, value)

    def register_buffer(self, name: str, tensor: torch.Tensor, *args, **kwargs) -> None:
        self._register_attribute(name, rp.State(tensor, None, None, np.shape(tensor)))
        super().register_buffer(name, tensor, *args, **kwargs)

    def register_parameter(self, name: str, param: nn.Parameter) -> None:
        self._register_attribute(name, rp.Parameter(param, None, None, np.shape(param)))
        super().register_parameter(name, param)

    def _get_attribute_family(
        self, type_name: str, family: Union[str, Tuple, List] = None
    ) -> dict:
        # - Get the attributes dictionary
        attr = super()._get_attribute_family(type_name, family)

        # - Cast it to TorchModuleParameters and return
        return TorchModuleParameters(**attr)

    def _register_module(self, name: str, mod):
        """
        Add a submodule to the module registry

        Args:
            name (str): The name of the submodule, extracted from the assigned attribute name
            mod (TorchModule): The submodule to register

        Raises:
            ValueError: If the assigned submodule is not a `TorchModule`
        """
        # - Check that the submodule is also Torch compatible
        if not isinstance(mod, TorchModule):
            raise ValueError(
                f"Submodules of a `TorchModule` must themselves all be `TorchModule`s. Trying to assign a `{mod.class_name}` as a submodule of a `{self.class_name}`"
            )

        # - Register the module
        super()._register_module(name, mod)

    def to_torch(self, use_torch_call: bool = True):
        """
        Convert the module to use the torch.nn.Module API

        Args:
            use_torch_call (bool): Use the torch-stype ``__call__()`` method for this object

        Returns:
            The converted object
        """

        def parameters(self, *args, **kwargs):
            return nn.Module.parameters(self, *args, **kwargs)

        self.parameters = types.MethodType(parameters, self)

        def repr(self, *args, **kwargs):
            return nn.Module.__repr__(self, *args, **kwargs)

        self._repr = types.MethodType(repr, self)

        for name, mod in self.modules().items():
            if isinstance(mod, TorchModule):
                setattr(self, name, mod.to_torch(use_torch_call=False))

        if use_torch_call:

            def call(self, *args, **kwargs):
                return nn.Module.__call__(self, *args, **kwargs)

            self._call = types.MethodType(call, self)

        return self

    @classmethod
    def from_torch(cls: type, obj: nn.Module, retain_torch_api: bool = False) -> None:
        """
        Convert a torch module into a Rockpool :py:class:`.TorchModule` in-place

        Args:
            obj (torch.nn.Module): Torch module to convert to a Rockpool
            retain_torch_api (bool): If ``True``, calling the resulting module will use the Torch API. Default: ``False``, convert the module to the Rockpool low-level API for :py:meth:`__call__`.
        """
        # - Check that we have a Torch ``nn.Module``
        if not isinstance(obj, nn.Module):
            raise TypeError("`from_torch` can only patch torch.nn.Module objects.")

        # - Patch a torch nn.Module to be a Rockpool TorchModule
        orig_call = obj.__call__
        orig_parameters = obj.parameters
        old_class_name = obj.__class__.__name__

        class TorchModulePatch(obj.__class__, TorchModule):
            def __init__(self):
                super().__init__(retain_torch_api=retain_torch_api)

            #
            # def __call__(self, *args, **kwargs):
            #     if retain_torch_api:
            #         return orig_call(*args, **kwargs)
            #     else:
            #         return super().__call__(*args, **kwargs)
            #
            # def parameters(self, *args, **kwargs):
            #     if retain_torch_api:
            #         return orig_parameters(*args, **kwargs)
            #     else:
            #         return super().parameters(*args, **kwargs)

            @property
            def class_name(self) -> str:
                return old_class_name

        obj.__class__ = TorchModulePatch
        obj.__old_class_name = old_class_name

        assert isinstance(obj, TorchModule)

        # - Ensure attribute registry is initialised
        _, __modules = obj._get_attribute_registry()

        # - Ensure other base-class attributes are set
        obj._shape = (None,)
        obj._spiking_input = False
        obj._spiking_output = False
        obj._name = obj._get_name()
        obj._submodulenames = []

        # - Identify torch buffers and parameters, and register them
        for name, param in obj.named_parameters(recurse=False):
            obj._register_attribute(name, rp.Parameter(param, None, None, param.shape))

        for name, buffer in obj.named_buffers(recurse=False):
            obj._register_attribute(name, rp.State(buffer, None, None, buffer.shape))

        # - Convert and register submodules
        for name, mod in obj.named_children():
            # - Convert submodule
            TorchModule.from_torch(mod, retain_torch_api=True)

            # - Assign submodule to Rockpool module dictionary
            __modules[name] = [mod, type(mod).__name__]
            obj._submodulenames.append(name)

    def json_to_param(self, jparam):

        for k, param in jparam.items():

            if isinstance(param, str):
                param = json.loads(param)

            if isinstance(param, dict):
                self.modules()[k].json_to_param(param)
            else:
                my_params = self.parameters()
                if isinstance(my_params[k], list):
                    my_params[k] = param
                elif isinstance(my_params[k], np.ndarray):
                    my_params[k] = np.array(param)
                elif isinstance(my_params[k], torch.Tensor):
                    my_params[k].data = torch.Tensor(param)
                elif isinstance(my_params[k], TorchModuleParameters):
                    self.modules()[k].json_to_param(param)
                else:
                    raise NotImplementedError(
                        f"{type(my_params[k])} not implemented to load. Please implement."
                    )

    def param_to_json(self, param):

        if isinstance(param, torch.Tensor):
            return json.dumps(param.detach().cpu().numpy().tolist())
        elif isinstance(param, np.ndarray):
            return json.dumps(param.tolist())
        elif isinstance(param, dict):
            try:
                return json.dumps(param)
            except:
                return_dict = {}
                for k, p in param.items():
                    return_dict[k] = self.param_to_json(p)
                return return_dict
        else:
            raise NotImplementedError(
                f"{type(param)} not implemented to save. Please implement."
            )

    def to_json(self):
        params = self.parameters()

        return self.param_to_json(params)

    def save(self, fn):
        with open(fn, "w+") as f:
            json.dump(self.to_json(), f)

    def load(self, fn):

        with open(fn, "r") as f:
            params = json.load(f)

        self.json_to_param(params)
