Full API summary for |project|
==============================

.. py:currentmodule::rockpool

.. autosummary::
    :toctree: _autosummary
    :recursive:

    rockpool


Base classes
------------

.. seealso:: :ref:`/basics/getting_started.ipynb` and :ref:`/basics/time_series.ipynb`.

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    nn.modules.Module
    nn.modules.TimedModule

Attribute types
~~~~~~~~~~~~~~~

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    parameters.Parameter
    parameters.State
    parameters.SimulationParameter

.. autosummary::
    :toctree: _autosummary

    parameters.Constant


Alternative base classes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    nn.modules.JaxModule
    nn.modules.TorchModule

Combinator modules
------------------

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    nn.combinators.FFwdStack
    nn.combinators.Sequential
    nn.combinators.Residual


Time series classes
-------------------

.. seealso:: :ref:`/basics/time_series.ipynb`.

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    timeseries.TimeSeries
    timeseries.TSContinuous
    timeseries.TSEvent

:py:class:`Module` subclasses
-----------------------------

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    nn.modules.Rate
    nn.modules.RateJax
    nn.modules.RateTorch

    nn.modules.LIF
    nn.modules.LIFJax
    nn.modules.LIFTorch

    nn.modules.aLIFTorch

    nn.modules.LIFNeuronTorch
    nn.modules.UpDownTorch

    nn.modules.Linear
    nn.modules.LinearJax
    nn.modules.LinearTorch

    nn.modules.Instant
    nn.modules.InstantJax
    nn.modules.InstantTorch

    nn.modules.ExpSyn
    nn.modules.ExpSynJax
    nn.modules.ExpSynTorch

    nn.modules.SoftmaxJax
    nn.modules.LogSoftmaxJax

    nn.modules.ButterMelFilter
    nn.modules.ButterFilter

:py:class:`Layer` subclasses from Rockpool v1
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These classes are deprecated, but are still usable via the high-level API, until they are converted to the v2 API.

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    nn.layers.Layer

    nn.layers.FFIAFBrian
    nn.layers.FFIAFSpkInBrian
    nn.layers.RecIAFBrian
    nn.layers.RecIAFSpkInBrian
    nn.layers.FFExpSynBrian
    nn.layers.RecDIAF

    nn.layers.FFIAFNest
    nn.layers.RecIAFSpkInNest
    nn.layers.RecAEIFSpkInNest

Conversion utilities
--------------------

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    nn.modules.timed_module.TimedModuleWrapper
    nn.modules.timed_module.LayerToTimedModule
    nn.modules.timed_module.astimedmodule

``Jax`` training utilities
---------------------------

.. autosummary::
    :toctree: _autosummary
    :template: module.rst

    training.jax_loss
    training.adversarial_jax

.. autosummary::
    :toctree: _autosummary

    training.adversarial_jax.pga_attack
    training.adversarial_jax.adversarial_loss

``PyTorch`` training utilities
---------------------------

.. autosummary::
    :toctree: _autosummary
    :recursive:
    :template: module.rst

    training.torch_loss

Xylo hardware support and simulation
------------------------------------

.. autosummary::
    :toctree: _autosummary

    devices.xylo.config_from_specification
    devices.xylo.load_config
    devices.xylo.save_config

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    devices.xylo.XyloSim
    devices.xylo.XyloSamna
    devices.xylo.AFE
    devices.xylo.DivisiveNormalisation

.. autosummary::
    :toctree: _autosummary
    :template: module.rst

    devices.xylo
    devices.xylo.xylo_devkit_utils

.. autosummary::
    :toctree: _autosummary

    devices.xylo.mapper

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    devices.xylo.XyloHiddenNeurons
    devices.xylo.XyloOutputNeurons

Graph tracing and mapping
-------------------------

Base modules

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    graph.GraphModuleBase
    graph.GraphModule
    graph.GraphNode
    graph.GraphHolder

.. autosummary::
    :toctree: _autosummary

    graph.graph_base.as_GraphHolder

Computational graph modules

.. autosummary::
    :toctree: _autosummary
    :template: class.rst

    graph.LinearWeights
    graph.GenericNeurons
    graph.AliasConnection
    graph.LIFNeuronWithSynsRealValue
    graph.RateNeuronWithSynsRealValue

.. autosummary::
    :toctree: _autosummary
    :template: module.rst

    graph.utils
