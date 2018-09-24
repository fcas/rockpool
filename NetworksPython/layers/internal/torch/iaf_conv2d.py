import numpy as np
import torch.nn as nn
from typing import Optional, Union, List, Tuple

# - Type alias for array-like objects
ArrayLike = Union[np.ndarray, List, Tuple]


class TorchSpikingConv2dLayer(nn.Module):
    def __init__(
        self,
        nInChannels: int = 1,
        nOutChannels: int = 1,
        kernel_size: ArrayLike = (1, 1),
        strides: ArrayLike = (1, 1),
        padding: ArrayLike = (0, 0, 0, 0),
        fVThresh: float = 8,
        fVThreshLow: Optional[float] = None,
        fVSubtract: Optional[float] = None,
        fVReset: float = 0,
    ):
        """
        Pytorch implementation of a spiking neuron with convolutional inputs
        SUBTRACT superseeds Reset value
        """
        super(TorchSpikingConv2dLayer, self).__init__()  # Init nn.Module
        self.pad = nn.ZeroPad2d(padding)
        self.conv = nn.Conv2d(
            nInChannels, nOutChannels, kernel_size=kernel_size, stride=strides
        )
        if fVThreshLow is not None:
            self.threshLower = nn.Threshold(-fVThresh, -fVThresh)  # Relu on the layer
        else:
            self.threshLower = None
        # Initialize neuron states
        self.fVSubtract = fVSubtract
        self.fVReset = fVReset
        self.fVThresh = fVThresh
        self.fVThreshLow = fVThreshLow

        # Layer convolutional properties
        self.nInChannels = nInChannels
        self.nOutChannels = nOutChannels
        self.kernel_size = kernel_size
        self.padding = padding
        self.strides = strides

        # Blank parameter place holders
        self.tsrNumSpikes = None
        self.tsrState = None

    def reset_states(self):
        """
        Reset the state of all neurons in this layer
        """
        self.tsrState.zero_()
        self.tsrState.zero_()

    def forward(self, tsrBinaryInput):
        # Determine no. of time steps from input
        nNumTimeSteps = len(tsrBinaryInput)

        # Convolve all inputs at once
        tsrConvOut = self.conv(self.pad(tsrBinaryInput))

        ## - Count number of spikes for each neuron in each time step
        # vnNumSpikes = np.zeros(tsrConvOut.shape[1:], int)

        # Local variables
        tsrState = self.tsrState
        fVSubtract = self.fVSubtract
        fVThresh = self.fVThresh
        fVThreshLow = self.fVThreshLow
        fVReset = self.fVReset

        # Initialize state as required
        # Create a vector to hold all output spikes
        if self.tsrNumSpikes is None:
            self.tsrNumSpikes = tsrConvOut.new_zeros(
                nNumTimeSteps, *tsrConvOut.shape[1:]
            ).int()

        self.tsrNumSpikes.zero_()
        tsrNumSpikes = self.tsrNumSpikes

        if self.tsrState is None:
            self.tsrState = tsrConvOut.new_zeros(tsrConvOut.shape[1:])

        tsrState = self.tsrState

        # Loop over time steps
        for iCurrentTimeStep in range(nNumTimeSteps):
            tsrState = tsrState + tsrConvOut[iCurrentTimeStep]

            # - Check threshold crossings for spikes
            vbRecSpikeRaster = tsrState >= fVThresh

            # - Reset or subtract from membrane state after spikes
            if fVSubtract is not None:
                while vbRecSpikeRaster.any():
                    # - Subtract from states
                    tsrState = tsrState - (fVSubtract * vbRecSpikeRaster.float())
                    # - Add to spike counter
                    tsrNumSpikes[iCurrentTimeStep] += vbRecSpikeRaster.int()
                    # - Neurons that are still above threshold will emit another spike
                    vbRecSpikeRaster = tsrState >= fVThresh
            else:
                # - Add to spike counter
                tsrNumSpikes[iCurrentTimeStep] = vbRecSpikeRaster
                # - Reset neuron states
                tsrState = (
                    vbRecSpikeRaster.float() * fVReset
                    + tsrState * (vbRecSpikeRaster ^ 1).float()
                )

            if fVThreshLow is not None:
                tsrState = self.threshLower(tsrState)  # Lower bound on the activation

        self.tsrState = tsrState
        self.tsrNumSpikes = tsrNumSpikes

        return tsrNumSpikes.float()  # Float is just to keep things compatible