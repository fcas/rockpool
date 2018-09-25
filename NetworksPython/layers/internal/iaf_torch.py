###
# iaf_torch.py - Classes implementing recurrent and feedforward layers consisting of standard IAF neurons in in torch (GPU)
###


# - Imports
import numpy as np
import torch

from ...timeseries import TSContinuous, TSEvent

from ..layer import Layer
from .timedarray_shift import TimedArray as TAShift

from typing import Optional, Union, Tuple, List

from time import time

# - Type alias for array-like objects
ArrayLike = Union[np.ndarray, List, Tuple]

# - Configure exports
__all__ = [
    "FFIAFTorch",
]

# - Absolute tolerance, e.g. for comparing float values
fTolAbs = 1e-9

## - FFIAFTorch - Class: define a spiking feedforward layer with spiking outputs
class FFIAFTorch(Layer):
    """ FFIAFTorch - Class: define a spiking feedforward layer with spiking outputs
    """

    ## - Constructor
    def __init__(
        self,
        mfW: np.ndarray,
        vfBias: Union[float, np.ndarray] = 0.015,
        tDt: float = 0.0001,
        fNoiseStd: float = 0,
        vtTauN: Union[float, np.ndarray] = 0.02,
        vfVThresh: Union[float, np.ndarray] = -0.055,
        vfVReset: Union[float, np.ndarray] = -0.065,
        vfVRest: Union[float, np.ndarray] = -0.065,
        tRefractoryTime=0,
        strName: str = "unnamed",
        bRecord: bool = False,
    ):
        """
        FFIAFTorch - Construct a spiking feedforward layer with IAF neurons, running on GPU, using torch
                     Inputs are continuous currents; outputs are spiking events

        :param mfW:             np.array MxN weight matrix.
        :param vfBias:          np.array Nx1 bias vector. Default: 10mA

        :param tDt:             float Time-step. Default: 0.1 ms
        :param fNoiseStd:       float Noise std. dev. per second. Default: 0

        :param vtTauN:          np.array Nx1 vector of neuron time constants. Default: 20ms

        :param vfVThresh:       np.array Nx1 vector of neuron thresholds. Default: -55mV
        :param vfVReset:        np.array Nx1 vector of neuron thresholds. Default: -65mV
        :param vfVRest:         np.array Nx1 vector of neuron thresholds. Default: -65mV

        :param tRefractoryTime: float Refractory period after each spike. Default: 0ms

        :param strName:         str Name for the layer. Default: 'unnamed'

        :param bRecord:         bool Record membrane potential during evolutions
        """

        # - Call super constructor (`asarray` is used to strip units)
        super().__init__(
            mfW=np.asarray(mfW),
            tDt=tDt,
            fNoiseStd=fNoiseStd,
            strName=strName,
        )

        # - Set device to cuda if available and determine how tensors should be instantiated
        if torch.cuda.is_available():
            self.device = torch.device('cuda')
            self.tensors = torch.cuda
        else:
            self.device = torch.device('cpu')
            print("Layer `{}`: Using CPU as CUDA is not available.".format(strName))
            self.tensors = torch

        # - Record neuron parameters
        self.vfVThresh = vfVThresh
        self.vfVReset = vfVReset
        self.vfVRest = vfVRest
        self.vtTauN = vtTauN
        self.vfBias = vfBias
        self.mfW = mfW
        self._bRecord = bRecord

        # - Store "reset" state
        self.reset_all()

    # @profile
    def evolve(
        self,
        tsInput: Optional[TSContinuous] = None,
        tDuration: Optional[float] = None,
        nNumTimeSteps: Optional[int] = None,
        bVerbose: bool = False,
        nMaxTimeStep: int = 2000,
    ) -> TSEvent:
        """
        evolve : Function to evolve the states of this layer given an input. Automatically splits evolution in batches,

        :param tsSpkInput:      TSContinuous  Input spike trian
        :param tDuration:       float    Simulation/Evolution time
        :param nNumTimeSteps:   int      Number of evolution time steps
        :param bVerbose:        bool     Currently no effect, just for conformity
        :param nMaxTimeStep:    int      Maximum no. of timesteps evolutions are split into.
        :return:            TSEvent  output spike series

        """
        
        # - Layer time step before evolution
        nTimeStepStart = self._nTimeStep

        # - Prepare time base
        mfInput, nNumTimeSteps = self._prepare_input(tsInput, tDuration, nNumTimeSteps)

        # - Evolve over batches and collect spike data
        lnSpikeTimeIndices = list()
        lnSpikeChannels = list()
        lmRecordedStates = list(self._vState.reshape(1,1,-1))  # List seems to reduce one dimension

        for mfCurrentInput, nCurrNumTS in self._batch_timesteps(mfInput, nNumTimeSteps, nMaxTimeStep):
            ltNewIndices, lnNewChannels, mNewRecordings = self._single_batch_evolution(mfCurrentInput, nCurrNumTS, bVerbose)
            lnSpikeTimeIndices += ltNewIndices
            lnSpikeChannels += lnNewChannels
            lmRecordedStates.append(mNewRecordings)

        # - Output timeseries
        vtSpikeTimings = np.array(lnSpikeTimeIndices) * self.tDt
        tseOut = TSEvent(vtSpikeTimings, lnSpikeChannels, strName="Layer `{}` spikes".format(self.strName))

        # - Store recorded states in timeseries
        if self._bRecord:
            vtRecordTimes = np.repeat(
                (nTimeStepStart + np.arange(nNumTimeSteps + 1 )) * self.tDt, 2
            )[1:]
            mfRecordStates = torch.cat(lmRecordedStates).cpu().numpy()
            self.tscRecorded = TSContinuous(vtRecordTimes, mfRecordStates)
        
        return tseOut


    def _batch_timesteps(
        self, mfInput: np.ndarray, nNumTimeSteps: int, nMaxTimeStep: int = None,
    ) -> (np.ndarray, int):
        """_batch_timesteps: Generator that returns the data in batches"""
        # - Handle None for nMaxTimeStep
        nMaxTimeStep = nNumTimeSteps if nMaxTimeStep is None else nMaxTimeStep
        nStart = 0
        while nStart < nNumTimeSteps:
            # - Endpoint of current batch
            nEnd = min(nStart + nMaxTimeStep, nNumTimeSteps)
            # - Data for current batch
            mfCurrentInput = mfInput[nStart:nEnd]
            yield mfCurrentInput, nEnd-nStart
            # - Update nStart
            nStart = nEnd

        
    def _single_batch_evolution(
        self,
        mfInput: np.ndarray,
        nNumTimeSteps: Optional[int] = None,
        bVerbose: bool = False,
    ) -> TSEvent:
        """
        evolve : Function to evolve the states of this layer given an input for a single batch

        :param mfInput:     np.ndarray   Input to neurons as matrix
        :param nNumTimeSteps:   int      Number of evolution time steps
        :param bVerbose:        bool     Currently no effect, just for conformity
        :return:            TSEvent  output spike series

        """

        # - Get synapse input to neurons
        mfNeuralInput, nNumTimeSteps = self._prepare_neural_input(mfInput, nNumTimeSteps)
        # - Include resting potential and bias in input for fewer computations
        mfNeuralInput += self._vfVRest + self._vfBias
        # - Tensor for collecting spike data
        mbSpiking = self.tensors.ByteTensor(nNumTimeSteps+1, self.nSize).fill_(0)
        # - Tensor for recording states
        if self._bRecord:
            mfRecordStates = self.tensors.FloatTensor(2*nNumTimeSteps, self.nSize).fill_(0)
        else:
            mfRecordStates = None
        # - Get local variables
        vState = self._vState.clone()
        vfAlpha = self._vfAlpha
        vfVThresh = self._vfVThresh
        vfVRest = self._vfVRest
        vfVReset = self._vfVReset

        for nStep in range(nNumTimeSteps):
            # - Incremental state update from input
            vState += vfAlpha * (mfNeuralInput[nStep] - vState)
            # - Store updated state before spike
            if self._bRecord:
                mfRecordStates[2*nStep] = vState
            # - Spiking
            vbSpiking = vState > vfVThresh
            # vState[vbSpiking] = vfVRest[vbSpiking]
            # - State reset
            vState += (vfVReset - vState) * vbSpiking.float()
            # - Store spikes
            mbSpiking[nStep] = vbSpiking
            # - Store updated state after spike
            if self._bRecord:
                mfRecordStates[2*nStep+1] = vState
            del vbSpiking

        # - Extract spike output data
        vnSpikeTimeIndices, vnChannels = np.nonzero(mbSpiking.cpu().numpy())
        vnSpikeTimeIndices += self._nTimeStep
        
        # - Store updated state and update clock
        self._vState = vState
        self._nTimeStep += nNumTimeSteps
        
        return list(vnSpikeTimeIndices), list(vnChannels), mfRecordStates

    # @profile
    def _prepare_neural_input(
        self,
        mfInput: np.array,
        nNumTimeSteps: Optional[int] = None,
    ) -> (np.ndarray, int):
        """
        _prepare_neural_input : Prepare the weighted, noisy synaptic input to the neurons
                                and return it together with number of evolution time steps

        :param tsSpkInput:      TSContinuous  Input spike trian
        :param tDuration:       float    Simulation/Evolution time
        :param nNumTimeSteps    int      Number of evolution time steps
        :return:
                mfNeuralInput   np.ndarray  Input to neurons
                nNumTimeSteps   int         Number of evolution time steps

        """
        # - Prepare mfInput
        mfInput = torch.from_numpy(mfInput).float().to(self.device)
        # - Weight inputs
        mfNeuralInput = torch.mm(mfInput, self._mfW)

        # - Add noise trace
        mfNeuralInput += (
            torch.randn(nNumTimeSteps, self.nSize).float().to(self.device)
            # - Standard deviation slightly smaller than expected (due to brian??),
            #   therefore correct with empirically found factor 1.63
            * self.fNoiseStd
            * torch.sqrt(2. * self._vtTauN / self.tDt)
            * 1.63
        )

        return mfNeuralInput, nNumTimeSteps

    def _prepare_input(
        self,
        tsInput: TSContinuous = None,
        tDuration: float = None,
        nNumTimeSteps: int = None,
    ) -> (torch.Tensor, int):
        """
        _prepare_input - Sample input, set up time base

        :param tsInput:       TimeSeries TxM or Tx1 Input signals for this layer
        :param tDuration:     float Duration of the desired evolution, in seconds
        :param nNumTimeSteps: int Number of evolution time steps

        :return: (vtTimeBase, mfInputStep, tDuration)
            mfInputStep:    Tensor (T1xN) Discretised input signal for layer
            nNumTimeSteps:  int Actual number of evolution time steps
        """
        if nNumTimeSteps is None:
            # - Determine nNumTimeSteps
            if tDuration is None:
                # - Determine tDuration
                assert (
                    tsInput is not None
                ), "Layer `{}`: One of `nNumTimeSteps`, `tsInput` or `tDuration` must be supplied".format(
                    self.strName
                )

                if tsInput.bPeriodic:
                    # - Use duration of periodic TimeSeries, if possible
                    tDuration = tsInput.tDuration

                else:
                    # - Evolve until the end of the input TImeSeries
                    tDuration = tsInput.tStop - self.t
                    assert tDuration > 0, (
                        "Layer `{}`: Cannot determine an appropriate evolution duration.".format(
                            self.strName
                        )
                        + " `tsInput` finishes before the current evolution time."
                    )
            nNumTimeSteps = int(np.floor((tDuration + fTolAbs) / self.tDt))
        else:
            assert isinstance(
                nNumTimeSteps, int
            ), "Layer `{}`: nNumTimeSteps must be of type int.".format(self.strName)

        # - Generate discrete time base
        vtTimeBase = self._gen_time_trace(self.t, nNumTimeSteps)

        if tsInput is not None:
            # - Make sure vtTimeBase matches tsInput
            if not isinstance(tsInput, TSEvent):
                if not tsInput.bPeriodic:
                    # - If time base limits are very slightly beyond tsInput.tStart and tsInput.tStop, match them
                    if (
                        tsInput.tStart - 1e-3 * self.tDt
                        <= vtTimeBase[0]
                        <= tsInput.tStart
                    ):
                        vtTimeBase[0] = tsInput.tStart
                    if (
                        tsInput.tStop
                        <= vtTimeBase[-1]
                        <= tsInput.tStop + 1e-3 * self.tDt
                    ):
                        vtTimeBase[-1] = tsInput.tStop

                # - Warn if evolution period is not fully contained in tsInput
                if not (tsInput.contains(vtTimeBase) or tsInput.bPeriodic):
                    print(
                        "Layer `{}`: Evolution period (t = {} to {}) ".format(
                            self.strName, vtTimeBase[0], vtTimeBase[-1]
                        )
                        + "not fully contained in input signal (t = {} to {})".format(
                            tsInput.tStart, tsInput.tStop
                        )
                    )

            # - Sample input trace and check for correct dimensions
            mfInputStep = self._check_input_dims(tsInput(vtTimeBase))

            # - Treat "NaN" as zero inputs
            mfInputStep[np.isnan(mfInputStep)] = 0

        else:
            # - Assume zero inputs
            mfSpikeRaster = np.zeros((nNumTimeSteps, self.nSizeIn))

        return (
            mfInputStep, nNumTimeSteps
        )

    def reset_state(self):
        """ .reset_state() - Method: reset the internal state of the layer
            Usage: .reset_state()
        """
        self.vState = self.vfVReset

    ### --- Properties

    @property
    def cOutput(self):
        return TSEvent

    @property
    def tRefractoryTime(self):
        return self._nRefractorySteps * self.tDt

    @tRefractoryTime.setter
    def tRefractoryTime(self, tNewTime):
        self._nRefractorySteps = int(np.round(tNewTime / self.tDt))
    
    @property
    def vState(self):
        return self._vState.cpu().numpy()

    @vState.setter
    def vState(self, vNewState):
        vNewState =         (
            np.asarray(self._expand_to_net_size(vNewState, "vState"))
        )
        self._vState = torch.from_numpy(vNewState).to(self.device).float()

    @property
    def vtTauN(self):
        return self._vtTauN.cpu().numpy()

    @vtTauN.setter
    def vtTauN(self, vtNewTauN):
        vtNewTauN = (
            np.asarray(self._expand_to_net_size(vtNewTauN, "vtTauN"))
        )
        self._vtTauN = torch.from_numpy(vtNewTauN).to(self.device).float()
        if (self.tDt >= self._vtTauN).any():
            print("Layer `{}`: tDt is larger than vtTauN. This can cause numerical instabilities.")

    @property
    def vfAlpha(self):
        return self._vfAlpha.cpu().numpy()

    @property
    def _vfAlpha(self):
        return self.tDt / self._vtTauN 

    @property
    def vfBias(self):
        return self._vfBias.cpu().numpy()

    @vfBias.setter
    def vfBias(self, vfNewBias):
        vfNewBias = (
            np.asarray(self._expand_to_net_size(vfNewBias, "vfBias"))
        )
        self._vfBias = torch.from_numpy(vfNewBias).to(self.device).float()

    @property
    def vfVThresh(self):
        return self._vfVThresh.cpu().numpy()

    @vfVThresh.setter
    def vfVThresh(self, vfNewVThresh):
        vfNewVThresh = (
            np.asarray(self._expand_to_net_size(vfNewVThresh, "vfVThresh"))
        )
        self._vfVThresh = torch.from_numpy(vfNewVThresh).to(self.device).float()

    @property
    def vfVRest(self):
        return self._vfVRest.cpu().numpy()

    @vfVRest.setter
    def vfVRest(self, vfNewVRest):
        vfNewVRest = (
            np.asarray(self._expand_to_net_size(vfNewVRest, "vfVRest"))
        )
        self._vfVRest = torch.from_numpy(vfNewVRest).to(self.device).float()

    @property
    def vfVReset(self):
        return self._vfVReset.cpu().numpy()

    @vfVReset.setter
    def vfVReset(self, vfNewVReset):
        vfNewVReset = (
            np.asarray(self._expand_to_net_size(vfNewVReset, "vfVReset"))
        )
        self._vfVReset = torch.from_numpy(vfNewVReset).to(self.device).float()

    @property
    def t(self):
        return self._nTimeStep * self.tDt

    @property
    def mfW(self):
        return self._mfW.cpu().numpy()

    @mfW.setter
    def mfW(self, mfNewW):
        mfNewW  = self._expand_to_shape(mfNewW, (self.nSizeIn, self.nSize), "mfW", bAllowNone=False)
        self._mfW = torch.from_numpy(mfNewW).to(self.device).float()


# - FFIAFSpkInTorch - Class: Spiking feedforward layer with spiking in- and outputs
class FFIAFSpkInTorch(FFIAFTorch):
    """ FFIAFSpkInTorch - Class: Spiking feedforward layer with spiking in- and outputs
    """

    ## - Constructor
    def __init__(
        self,
        mfW: np.ndarray,
        vfBias: np.ndarray = 0.01,
        tDt: float = 0.0001,
        fNoiseStd: float = 0,
        vtTauN: np.ndarray = 0.02,
        vtTauS: np.ndarray = 0.02,
        vfVThresh: np.ndarray = -0.055,
        vfVReset: np.ndarray = -0.065,
        vfVRest: np.ndarray = -0.065,
        tRefractoryTime=0,
        strName: str = "unnamed",
        bRecord: bool = False,
    ):
        """
        FFIAFSpkInTorch - Construct a spiking feedforward layer with IAF neurons, running on GPU, using torch
                          in- and outputs are spiking events

        :param mfW:             np.array MxN weight matrix.
        :param vfBias:          np.array Nx1 bias vector. Default: 10mA

        :param tDt:             float Time-step. Default: 0.1 ms
        :param fNoiseStd:       float Noise std. dev. per second. Default: 0

        :param vtTauN:          np.array Nx1 vector of neuron time constants. Default: 20ms
        :param vtTauS:          np.array Nx1 vector of synapse time constants. Default: 20ms

        :param vfVThresh:       np.array Nx1 vector of neuron thresholds. Default: -55mV
        :param vfVReset:        np.array Nx1 vector of neuron thresholds. Default: -65mV
        :param vfVRest:         np.array Nx1 vector of neuron thresholds. Default: -65mV

        :param tRefractoryTime: float Refractory period after each spike. Default: 0ms

        :param strName:         str Name for the layer. Default: 'unnamed'

        :param bRecord:         bool Record membrane potential during evolutions
        """

        # - Call super constructor (`asarray` is used to strip units)
        super().__init__(
            mfW=mfW,
            vfBias=vfBias,
            tDt=tDt,
            fNoiseStd=fNoiseStd,
            vtTauN=vtTauN,
            vfVThresh=vfVThresh,
            vfVReset=vfVReset,
            vfVRest=vfVRest,
            tRefractoryTime=tRefractoryTime,
            strName=strName,
            bRecord=bRecord,
        )

        # - Record neuron parameters
        self.vtTauS = vtTauS


    def _prepare_neural_input(
        self,
        mfInput: np.array,
        nNumTimeSteps: Optional[int] = None,
    ) -> (np.ndarray, int):
        """
        _prepare_neural_input : Prepare the weighted, noisy synaptic input to the neurons
                                and return it together with number of evolution time steps

        :param tsSpkInput:      TSContinuous  Input spike trian
        :param tDuration:       float    Simulation/Evolution time
        :param nNumTimeSteps    int      Number of evolution time steps
        :return:
                mfNeuralInput   np.ndarray  Input to neurons
                nNumTimeSteps   int         Number of evolution time steps

        """
        # - Prepare mfInput
        mfInput = torch.from_numpy(mfInput).float().to(self.device)
        # - Weigh inputs
        mfWeightedInput = torch.mm(mfInput,self._mfW)

        # - Add noise trace
        mfWeightedInput += (
            torch.randn(nNumTimeSteps, self.nSize).to(self.device).float()
            # - Standard deviation slightly smaller than expected (due to brian??),
            #   therefore correct with empirically found factor 1.63
            * self.fNoiseStd
            * torch.sqrt(2. * self._vtTauN / self.tDt)
            * 1.63
        )

        # - Reshape input for convolution
        mfWeightedInput = mfWeightedInput.t().reshape(1,self.nSize,-1)

        # - Apply exponential filter to input
        vtTimes = torch.arange(nNumTimeSteps).to(self.device).reshape(1,-1).float() * self.tDt
        mfKernels = torch.exp(-vtTimes / self._vtTauS.reshape(-1,1))
        # - Reverse on time axis and reshape to match convention of pytorch
        mfKernels = mfKernels.flip(1).reshape(self.nSize, 1, nNumTimeSteps)
        # - Object for applying convolution
        convSynapses = torch.nn.Conv1d(
            self.nSize, self.nSize, nNumTimeSteps, padding=nNumTimeSteps-1, groups=self.nSize, bias=False
        ).to(self.device)
        convSynapses.weight.data = mfKernels
        # - Filtered synaptic currents
        mfNeuralInput = convSynapses(mfWeightedInput)[0].detach().t()[:nNumTimeSteps]

        return mfNeuralInput, nNumTimeSteps

    def _prepare_input(
        self,
        tsInput: Optional[TSEvent] = None,
        tDuration: Optional[float] = None,
        nNumTimeSteps: Optional[int] = None,
    ) -> (np.ndarray, int):
        """
        _prepare_input - Sample input, set up time base

        :param tsInput:      TimeSeries TxM or Tx1 Input signals for this layer
        :param tDuration:    float Duration of the desired evolution, in seconds
        :param nNumTimeSteps int Number of evolution time steps

        :return:
            mfSpikeRaster:    Tensor Boolean raster containing spike info
            nNumTimeSteps:    ndarray Number of evlution time steps
        """
        if nNumTimeSteps is None:
            # - Determine nNumTimeSteps
            if tDuration is None:
                # - Determine tDuration
                assert (
                    tsInput is not None
                ), "Layer {}: One of `nNumTimeSteps`, `tsInput` or `tDuration` must be supplied".format(
                    self.strName
                )

                if tsInput.bPeriodic:
                    # - Use duration of periodic TimeSeries, if possible
                    tDuration = tsInput.tDuration

                else:
                    # - Evolve until the end of the input TImeSeries
                    tDuration = tsInput.tStop - self.t
                    assert tDuration > 0, (
                        "Layer {}: Cannot determine an appropriate evolution duration.".format(
                            self.strName
                        )
                        + "`tsInput` finishes before the current "
                        "evolution time."
                    )
            # - Discretize tDuration wrt self.tDt
            nNumTimeSteps = int((tDuration + fTolAbs) // self.tDt)
        else:
            assert isinstance(
                nNumTimeSteps, int
            ), "Layer `{}`: nNumTimeSteps must be of type int.".format(self.strName)

        # - End time of evolution
        tFinal = self.t + nNumTimeSteps * self.tDt

        # - Extract spike timings and channels
        if tsInput is not None:
            # Extract spike data from the input variable
            __, __, mfSpikeRaster, __ = tsInput.raster(
                tDt=self.tDt,
                tStart=self.t,
                tStop=(self._nTimeStep + nNumTimeSteps) * self._tDt,
                vnSelectChannels=np.arange(self.nSizeIn), ## This causes problems when tsInput has no events in some channels
            )
            # - Convert to supportedformat
            mfSpikeRaster = mfSpikeRaster.astype(int)
            # - Make sure size is correct
            mfSpikeRaster = mfSpikeRaster[:nNumTimeSteps, :]

        else:
            mfSpikeRaster = np.zeros((nNumTimeSteps, self.nSizeIn))

        return mfSpikeRaster, nNumTimeSteps

    @property
    def vtTauS(self):
        return self._vtTauS.cpu().numpy()

    @vtTauS.setter
    def vtTauS(self, vtNewTauS):
        vtNewTauS = (
            np.asarray(self._expand_to_net_size(vtNewTauS, "vtTauS"))
        )
        self._vtTauS = torch.from_numpy(vtNewTauS).to(self.device).float()

