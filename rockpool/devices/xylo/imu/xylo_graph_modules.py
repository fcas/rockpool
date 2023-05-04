"""
Xylo graph modules for use with tracing and mapping
"""
from rockpool.devices.xylo.syns61201 import Xylo2Neurons

from dataclasses import dataclass, field

__all__ = ["XyloIMUNeurons", "XyloIMUHiddenNeurons", "XyloIMUOutputNeurons"]


class XyloIMUNeurons(Xylo2Neurons):
    """
    Base class for all Xylo graph module classes
    """

    def __init__(self, *args, **kwargs):
        super(XyloIMUNeurons, self).__init__(*args, **kwargs)


@dataclass(eq=False, repr=False)
class XyloIMUHiddenNeurons(XyloIMUNeurons):
    """
    A :py:class:`.graph.GraphModule` encapsulating Xylo IMU hidden neurons
    """

    def __post_init__(self, *args, **kwargs):
        if len(self.input_nodes) != len(self.output_nodes):
            if len(self.input_nodes) != 2 * len(self.output_nodes):
                raise ValueError(
                    "Number of input nodes must be 1* or 2* number of output nodes"
                )

        super().__post_init__(self, *args, **kwargs)


@dataclass(eq=False, repr=False)
class XyloIMUOutputNeurons(XyloIMUNeurons):
    """
    A :py:class:`.graph.GraphModule` encapsulating Xylo IMU output neurons
    """

    def __post_init__(self, *args, **kwargs):
        if len(self.input_nodes) != len(self.output_nodes):
            raise ValueError(
                "Number of input nodes must be equal to number of output nodes"
            )

        super().__post_init__(self, *args, **kwargs)
