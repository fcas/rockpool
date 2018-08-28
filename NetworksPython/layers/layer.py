import numpy as np
import warnings
from abc import ABC, abstractmethod

from ..timeseries import TimeSeries, TSContinuous, TSEvent

# - Configure exports
__all__ = ["Layer"]


# - Absolute tolerance, e.g. for comparing float values
fTolAbs = 1e-9

### --- Convenience functions


def to_scalar(value, sClass: str = None):
    # - Check the value is a scalar
    assert np.size(value) == 1, "The value muste be a scalar"

    if sClass is not None:
        return np.asscalar(np.array(value).astype(sClass))
    else:
        return np.asscalar(np.array(value))


### --- Implements the Layer abstract class


class Layer(ABC):
    def __init__(
        self,
        mfW: np.ndarray,
        tDt: float = 1,
        fNoiseStd: float = 0,
        strName: str = "unnamed",
    ):
        """
        Layer class - Implement an abstract layer of neurons (no implementation)

        :param mfW:         np.ndarray Weight matrix for this layer
        :param tDt:         float Time-step used for evolving this layer. Default: 1
        :param fNoiseStd:   float Std. Dev. of state noise when evolving this layer. Default: 0. Defined as the expected
                                    std. dev. after 1s of integration time
        :param strName:       str Name of this layer. Default: 'unnamed'
        """

        # - Assign properties
        if strName is None:
            self.strName = "unnamed"
        else:
            self.strName = strName

        self._mfW = mfW
        self._nSizeIn, self._nSize = mfW.shape

        # - Check and assign tDt and fNoiseStd
        assert (
            np.size(tDt) == 1 and np.size(fNoiseStd) == 1
        ), "Layer `{}`: `tDt` and `fNoiseStd` must be scalars.".format(
            self.strName
        )

        self._tDt = tDt
        self.fNoiseStd = fNoiseStd
        self._nTimeStep = 0

    ### --- Common methods

    def _prepare_input(
        self,
        tsInput: TimeSeries = None,
        tDuration: float = None,
        nNumTimeSteps: int = None,
    ) -> (np.ndarray, np.ndarray, float):
        """
        _prepare_input - Sample input, set up time base

        :param tsInput:       TimeSeries TxM or Tx1 Input signals for this layer
        :param tDuration:     float Duration of the desired evolution, in seconds
        :param nNumTimeSteps: int Number of evolution time steps

        :return: (vtTimeBase, mfInputStep, tDuration)
            vtTimeBase:     ndarray T1 Discretised time base for evolution
            mfInputStep:    ndarray (T1xN) Discretised input signal for layer
            nNumTimeSteps:  int Actual number of evolution time steps
        """

        if nNumTimeSteps is None:
            # - Determine nNumTimeSteps
            if tDuration is None:
                # - Determine tDuration
                assert (
                    tsInput is not None
                ), "Layer `{}`: One of `tsInput` or `tDuration` must be supplied".format(
                    self.strName
                )

                if tsInput.bPeriodic:
                    # - Use duration of periodic TimeSeries, if possible
                    tDuration = tsInput.tDuration

                else:
                    # - Evolve until the end of the input TImeSeries
                    tDuration = tsInput.tStop - self.t
                    assert tDuration > 0, (
                        "Layer `{}`: Cannot determine an appropriate evolution duration.".format(self.strName)
                         + " `tsInput` finishes before the current evolution time."
                    )
            nNumTimeSteps = (tDuration+fTolAbs) // self.tDt
        else:
            assert (
                isinstance(nNumTimeSteps, int)
            ), "Layer `{}`: nNumTimeSteps must be of type int.".format(self.strName)

        # - Generate discrete time base
        vtTimeBase = self._gen_time_trace(self.t, nNumTimeSteps)

        # - Make sure vtTimeBase matches tsInput
        if tsInput is not None:
            if not tsInput.bPeriodic:
                # - If time base limits are very slightly beyond tsInput.tStart and tsInput.tStop, match them
                if tsInput.tStart - 1e-3*self.tDt <= vtTimeBase[0] <= tsInput.tStart:
                    vtTimeBase[0] = tsInput.tStart
                if tsInput.tStop <= vtTimeBase[-1] <= tsInput.tStop + 1e-3*self.tDt:
                    vtTimeBase[-1] = tsInput.tStop

            if not isinstance(tsInput, TSEvent):
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
            mfInputStep[np.where(np.isnan(mfInputStep))] = 0

        else:
            # - Assume zero inputs
            mfInputStep = np.zeros((np.size(vtTimeBase), self.nSizeIn))

        return vtTimeBase, mfInputStep, nNumTimeSteps

    def _check_input_dims(self, mfInput: np.ndarray) -> np.ndarray:
        """
        Verify if dimension of input matches layer instance. If input
        dimension == 1, scale it up to self._nSizeIn by repeating signal.
            mfInput : np.ndarray with input data
            return : mfInput, possibly with dimensions repeated
        """
        # - Replicate `tsInput` if necessary
        if mfInput.ndim == 1 or (mfInput.ndim > 1 and mfInput.shape[1]) == 1:
            mfInput = np.repeat(mfInput.reshape((-1, 1)), self._nSizeIn, axis=1)
        else:
            # - Check dimensionality of input
            assert (
                mfInput.shape[1] == self._nSizeIn
            ), "Layer `{}`: Input dimensionality {} does not match layer input size {}.".format(
                self.strName, mfInput.shape[1], self._nSizeIn
            )

        # - Return possibly corrected input
        return mfInput

    def _gen_time_trace(self, tStart: float, nNumTimeSteps: int) -> np.ndarray:
        """
        Generate a time trace starting at tStart, of length nNumTimeSteps+1 with
        time step length self._tDt. Make sure it does not go beyond
        tStart+tDuration.

        :return vtTimeTrace, tDuration
        """
        # - Generate a trace
        vtTimeTrace = np.arange(nNumTimeSteps+1) * self._tDt + tStart

        return vtTimeTrace

    def _expand_to_net_size(
        self, oInput, sVariableName: str = "input", bAllowNone: bool = True
    ) -> np.ndarray:
        """
        _expand_to_net_size: Replicate out a scalar to the size of the layer

        :param oInput:          scalar or array-like (N)
        :param sVariableName:   str Name of the variable to include in error messages
        :param bAllowNone:      bool Allow None as argument for oInput
        :return:                np.ndarray (N) vector
        """
        if not bAllowNone:
            assert oInput is not None, "Layer `{}`: `{}` must not be None".format(
                self.strName, sVariableName
            )

        if np.size(oInput) == 1:
            # - Expand input to vector
            oInput = np.repeat(oInput, self.nSize)

        assert (
            np.size(oInput) == self.nSize
        ), "Layer `{}`: `{}` must be a scalar or have {} elements".format(
            self.strName, sVariableName, self.nSize
        )

        # - Return object of correct shape
        return np.reshape(oInput, self.nSize)

    def _expand_to_weight_size(
        self, oInput, sVariableName: str = "input", bAllowNone: bool = True
    ) -> np.ndarray:
        """
        _expand_to_weight_size: Replicate out a scalar to the size of the layer's weights

        :param oInput:          scalar or array-like (NxN)
        :param sVariableName:   str Name of the variable to include in error messages
        :param bAllowNone:      bool Allow None as argument for oInput
        :return:                np.ndarray (NxN) vector
        """

        if not bAllowNone:
            assert oInput is not None, "Layer `{}`: `{}` must not be None".format(
                self.strName, sVariableName
            )

        if np.size(oInput) == 1:
            # - Expand input to matrix
            oInput = np.repeat(oInput, (self.nSize, self.nSize))

        assert (
            np.size(oInput) == self.nSize ** 2
        ), "Layer `{}`: `{}` must be a scalar or have {} elements".format(
            self.strName, sVariableName, self.nSize ** 2
        )

        # - Return object of correct size
        return np.reshape(oInput, (self.nSize, self.nSize))

    ### --- String representations

    def __str__(self):
        return '{} object: "{}" [{} {} in -> {} {} out]'.format(
            self.__class__.__name__,
            self.strName,
            self.nSizeIn,
            self.cInput.__name__,
            self.nSize,
            self.cOutput.__name__,
        )

    def __repr__(self):
        return self.__str__()

    ### --- State evolution methods

    @abstractmethod
    def evolve(self, tsInput: TimeSeries = None, tDuration: float = None) -> TimeSeries:
        """
        evolve - Abstract method to evolve the state of this layer

        :param tsInput:     TimeSeries (TxM) External input trace to use when evolving the layer
        :param tDuration:   float Duration in seconds to evolve the layer
        :return:            TimeSeries (TxN) Output of this layer
        """
        pass

    # @abstractmethod
    # def stream(self,
    #            tDuration: float,
    #            tDt: float,
    #            bVerbose: bool = False,
    #           ) -> TimeSeries:
    #     """
    #     stream - Abstract method to evolve the state of this layer, in a streaming format
    #
    #     :param tDuration: float Total duration to be streamed
    #     :param tDt:       float Streaming time-step (multiple of layer.tDt)
    #
    #     :yield TimeSeries raw tuple representation on each time step
    #     """
    #     pass

    def reset_state(self):
        """
        reset_state - Reset the internal state of this layer. Sets state to zero

        :return: None
        """
        self.vState = np.zeros(self.nSize)

    def reset_time(self):
        """
        reset_time - Reset the internal clock
        :return:
        """
        self._nTimeStep = 0

    def randomize_state(self):
        """
        randomize_state - Randomise the internal state of this layer

        :return: None
        """
        self.vState = np.random.rand(self.nSize)

    def reset_all(self):
        self.reset_time()
        self.reset_state()

    #### --- Properties

    @property
    def cOutput(self):
        return TSContinuous

    @property
    def cInput(self):
        return TSContinuous

    @property
    def nSize(self) -> int:
        return self._nSize

    @property
    def nSizeIn(self) -> int:
        return self._nSizeIn

    @property
    def tDt(self) -> float:
        return self._tDt

    @tDt.setter
    def tDt(self, fNewDt: float):
        self._tDt = to_scalar(fNewDt)

    @property
    def mfW(self) -> np.ndarray:
        return self._mfW

    @mfW.setter
    def mfW(self, mfNewW: np.ndarray):
        assert (mfNewW is not None), "Layer `{}`: mfW must not be None.".format(
            self.strName
        )

        # - Ensure weights are at least 2D
        try:
            assert mfNewW.ndim >= 2
        except AssertionError:
            warnings.warn("Layer `{}`: `mfNewW must be at least of dimension 2".format(self.strName))
            mfNewW = np.atleast_2d(mfNewW)

        # - Check dimensionality of new weights
        assert (
            mfNewW.size == self.nSizeIn * self.nSize
        ), "Layer `{}`: `mfNewW` must be of shape {}".format(
            (self.strName, self.nSizeIn, self.nSize)
        )

        # - Save weights with appropriate size
        self._mfW = np.reshape(mfNewW, (self.nSizeIn, self.nSize))

    @property
    def vState(self):
        return self._vState

    @vState.setter
    def vState(self, vNewState):
        assert (
            np.size(vNewState) == self.nSize
        ), "Layer `{}`: `vNewState` must have {} elements".format(
            self.strName, self.nSize
        )

        self._vState = vNewState

    @property
    def fNoiseStd(self):
        return self._fNoiseStd

    @fNoiseStd.setter
    def fNoiseStd(self, fNewNoiseStd):
        self._fNoiseStd = to_scalar(fNewNoiseStd)

    @property
    def t(self):
        return self._nTimeStep * self.tDt

    @t.setter
    def t(self, new_t):
        self._nTimeStep = new_t // self.tDt
    
    # - Temporary, for maintaining compatibility with layers that still use _t
    @property
    def _t(self):
        return self._nTimeStep * self.tDt

    @_t.setter
    def _t(self, new_t):
        self._nTimeStep = new_t // self.tDt
    
    
