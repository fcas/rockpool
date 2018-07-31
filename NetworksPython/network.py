###
# network.py - Code for encapsulating networks
###

### --- Imports
import numpy as np

import copy

from typing import Callable

from .timeseries import TimeSeries
from .layers.layer import Layer


# - Configure exports
__all__ = ["Network"]

# - Relative tolerance for float comparions
fTolRel = 1e-5
fTolAbs = 1e-8

### --- Helper functions


def isMultiple(a: float, b: float, fTolRel: float = fTolRel) -> bool:
    """
    isMultiple - Check whether a%b is 0 within some tolerance.
    :param a: float The number that may be multiple of b
    :param b: float The number a may be a multiple of
    :param fTolRel: float Relative tolerance
    :return bool: True if a is a multiple of b within some tolerance
    """
    fMinRemainder = min(a % b, b - a % b)
    return fMinRemainder < fTolRel * b


### --- Network class


class Network:
    def __init__(self, *layers: Layer):
        """
        Network - Super class to encapsulate several Layers, manage signal routing

        :param layers:   Layers to be added to the network. They will
                         be connected in series. The Order in which
                         they are received determines the order in
                         which they are connected. First layer will
                         receive external input
        """

        # - Network time
        self._t = 0

        # Maintain set of all layers
        self.setLayers = set()

        if layers:
            # - First layer receives external input
            self.lyrInput = self.add_layer(layers[0], bExternalInput=True)

            # - Keep track of most recently added layer
            lyrLastLayer = layers[0]

            # - Add and connect subsequent layers
            for lyr in layers[1:]:
                self.add_layer(lyr, lyrInput=lyrLastLayer)
                lyrLastLayer = lyr

            # - Handle to last layer
            self.lyrOutput = lyrLastLayer

        # - Set evolution order if no layers have been connected
        if not hasattr(self, "lEvolOrder"):
            self.lEvolOrder = self._evolution_order()

    def add_layer(
        self,
        lyr: Layer,
        lyrInput: Layer = None,
        lyrOutput: Layer = None,
        bExternalInput: bool = False,
        bVerbose: bool = False,
    ) -> Layer:
        """
        add_layer - Add a new layer to the network

        Add lyr to self and to self.setLayers. Its attribute name
        is 'lyr'+lyr.strName. Check whether layer with this name
        already exists (replace anyway).
        Connect lyr to lyrInput and lyrOutput.

        :param lyr:             Layer layer to be added to self
        :param lyrInput:        Layer input layer to lyr
        :param lyrOutput:       Layer layer to which lyr is input layer
        :param bExternalInput:  bool This layer receives external input (Default: False)
        :param bVerbose:        bool Print feedback about layer addition (Default: False)

        :return:                Layer lyr
        """
        # - Check whether layer time matches network time
        assert lyr.t == self.t, (
            "Layer time must match network time "
            + "(network: t={}, layer: t={})".format(self.t, lyr.t)
        )

        # - Check whether self already contains a layer with the same name as lyr.
        if hasattr(self, lyr.strName):
            # - Check if layers are the same object.
            if getattr(self, lyr.strName) is lyr:
                print("Layer `{}` is already part of the network".format(lyr.strName))
                return lyr
            else:
                sNewName = lyr.strName
                # - Find a new name for lyr.
                while hasattr(self, sNewName):
                    sNewName = self._new_name(sNewName)
                if bVerbose:
                    print(
                        "A layer with name `{}` already exists.".format(lyr.strName)
                        + "The new layer will be renamed to  `{}`.".format(sNewName)
                    )
                lyr.strName = sNewName

        # - Add set of input layers and flag to determine if lyr receives external input
        lyr.lyrIn = None
        lyr.bExternalInput = bExternalInput

        # - Add lyr to the network
        setattr(self, lyr.strName, lyr)
        if bVerbose:
            print("Added layer `{}` to network\n".format(lyr.strName))

        # - Update inventory of layers
        self.setLayers.add(lyr)

        # - Connect in- and outputs
        if lyrInput is not None:
            self.connect(lyrInput, lyr)
        if lyrOutput is not None:
            self.connect(lyr, lyrOutput)

        # - Make sure evolution order is updated if it hasn't been before
        if lyrInput is None and lyrOutput is None:
            self.lEvolOrder = self._evolution_order()

        return lyr

    @staticmethod
    def _new_name(strName: str) -> str:
        """
        _new_name: Generate a new name by first checking whether
                  the old name ends with '_i', with i an integer.
                  If so, replace i by i+1, otherwise append '_0'
        :param strName:   str - Name to be modified
        :return:        str - Modified name
        """

        # - Check wheter strName already ends with '_...'
        lsSplitted = strName.split("_")
        if len(lsSplitted) > 1:
            try:
                # - If the part after the last '_' is an integer, raise it by 1
                i = int(lsSplitted[-1])
                lsSplitted[-1] = str(i + 1)
                sNewName = "_".join(lsSplitted)
            except ValueError:
                sNewName = strName + "_0"
        else:
            sNewName = strName + "_0"

        return sNewName

    def remove_layer(self, lyrDel: Layer):
        """
        remove_layer: Remove a layer from the network by removing it
                      from the layer inventory and make sure that no
                      other layer receives input from it.
        :param lyrDel: Layer to be removed from network
        """

        # - Remove connections from lyrDel to others
        for lyr in self.setLayers:
            if lyrDel is lyr.lyrIn:
                lyr.lyrIn = None

        # - Remove lyrDel from the inventory and delete it
        self.setLayers.remove(lyrDel)

        # - Reevaluate the layer evolution order
        self.lEvolOrder = self._evolution_order()

    def connect(self, lyrSource: Layer, lyrTarget: Layer, bVerbose: bool = False):
        """
        connect: Connect two layers by defining one as the input layer
                 of the other.
        :param lyrSource:   The source layer
        :param lyrTarget:   The target layer
        :param bVerbose:    bool Flag indicating whether to print feedback
        """

        # - Make sure that layer dimensions match
        if lyrSource.nSize != lyrTarget.nDimIn:
            raise NetworkError(
                "Dimensions of layers `{}` (nSize={}) and `{}`".format(
                    lyrSource.strName, lyrSource.nSize, lyrTarget.strName
                )
                + " (nDimIn={}) do not match".format(lyrTarget.nDimIn)
            )

        # - Check for compatible input / output
        if lyrSource.cOutput != lyrTarget.cInput:
            raise NetworkError(
                "Input / output classes of layer `{}` (cOutput = {})".format(
                    lyrSource.strName, lyrSource.cOutput.__name__
                )
                + " and `{}` (cInput = {}) do not match".format(
                    lyrTarget.strName, lyrTarget.cInput.__name__
                )
            )

        # - Add source layer to target's set of inputs
        lyrTarget.lyrIn = lyrSource

        # - Make sure that the network remains a directed acyclic graph
        #   and reevaluate evolution order
        try:
            self.lEvolOrder = self._evolution_order()
            if bVerbose:
                print(
                    "Layer `{}` now receives input from layer `{}` \n".format(
                        lyrTarget.strName, lyrSource.strName
                    )
                )
        except NetworkError as e:
            lyrTarget.lyrIn = None
            raise e

    def disconnect(self, lyrSource: Layer, lyrTarget: Layer):
        """
        disconnect: Remove the connection between two layers by setting
                    the input of the target layer to None.
        :param lyrSource:   The source layer
        :param lyrTarget:   The target layer
        """

        # - Check whether layers are connected at all
        if lyrTarget.lyrIn is lyrSource:
            # - Remove the connection
            lyrTarget.lyrIn = None
            print(
                "Layer {} no longer receives input from layer `{}`".format(
                    lyrTarget.strName, lyrSource.strName
                )
            )

            # - Reevaluate evolution order
            try:
                self.lEvolOrder = self._evolution_order()
            except NetworkError as e:
                raise e

        else:
            print(
                "There is no connection from layer `{}` to layer `{}`".format(
                    lyrSource.strName, lyrTarget.strName
                )
            )

    def _evolution_order(self) -> list:
        """
        _evolution_order() - Determine the order in which layers are evolved. Requires Network
        to be a directed acyclic graph, otherwise evolution has to happen
        timestep-wise instead of layer-wise.
        """

        # - Function to find next evolution layer
        def next_layer(setCandidates: set) -> Layer:
            while True:
                try:
                    lyrCandidate = setCandidates.pop()
                # If no candidate is left, raise an exception
                except KeyError:
                    raise NetworkError("Cannot resolve evolution order of layers")
                    # Could implement timestep-wise evolution...
                else:
                    # - If there is a candidate and none of the remaining layers
                    #   is its input layer, this will be the next
                    if not (lyrCandidate.lyrIn in setlyrRemaining):
                        return lyrCandidate

        # - Set of layers that are not in evolution order yet
        setlyrRemaining = self.setLayers.copy()

        # # - Begin with input layer
        # lOrder = [self.lyrInput]
        # setlyrRemaining.remove(self.lyrInput)
        lOrder = []

        # - Loop through layers
        while bool(setlyrRemaining):
            # - Find the next layer to be evolved
            lyrNext = next_layer(setlyrRemaining.copy())
            lOrder.append(lyrNext)
            setlyrRemaining.remove(lyrNext)

        # - Return a list with the layers in their evolution order
        return lOrder

    def evolve(
        self,
        tsExternalInput: TimeSeries = None,
        tDuration: float = None,
        bVerbose: bool = True,
    ) -> dict:
        """
        evolve - Evolve each layer in the network according to self.lEvolOrder.
                 For layers with bExternalInput==True their input is
                 tsExternalInput. If not but an input layer is defined, it
                 will be the output of that, otherwise None.
                 Return a dict with each layer's output.
        :param tsExternalInput:  TimeSeries with external input data.
        :param tDuration:        float - duration over which netŵork should
                                         be evolved. If None, evolution is
                                         over the duration of tsExternalInput
        :param bVerbose:         bool - Print info about evolution state
        :return:                 Dict with each layer's output time Series
        """

        # - Determine default duration
        if tDuration is None:
            assert (
                tsExternalInput is not None
            ), "One of `tsExternalInput` or `tDuration` must be supplied"

            if tsExternalInput.bPeriodic:
                # - Use duration of periodic TimeSeries, if possible
                tDuration = tsExternalInput.tDuration

            else:
                # - Evolve until the end of the input TimeSeries
                tDuration = tsExternalInput.tStop - self.t
                assert tDuration > 0, (
                    "Cannot determine an appropriate evolution duration. "
                    + "`tsExternalInput` finishes before the current evolution time."
                )
                # - Correct tDuration in case of rounding errors
                tDuration = int(np.round(tDuration / self.lEvolOrder[0].tDt)) * self.lEvolOrder[0].tDt

        # - List of layers where tDuration is not a multiple of tDt
        llyrDtMismatch = list(
            filter(lambda lyr: not isMultiple(tDuration, lyr.tDt), self.lEvolOrder)
        )

        # - Throw an exception if llyrDtMismatch is not empty, showing for
        #   which layers there is a mismatch
        if llyrDtMismatch:
            strLayers = ", ".join(
                ("{}: tDt={}".format(lyr.strName, lyr.tDt) for lyr in llyrDtMismatch)
            )
            raise ValueError(
                "`tDuration` ({}) is not a multiple of `tDt`".format(tDuration)
                + " for the following layer(s):\n"
                + strLayers
            )
            # - Correct tDuration in case of rounding errors
            tDuration = int(np.round(tDuration / self.lEvolOrder[0].tDt)) * self.lEvolOrder[0].tDt


        # - Set external input name if not set already
        if tsExternalInput.strName is None:
            tsExternalInput.strName = 'External input'

        # - Dict to store external input and each layer's output time series
        dtsSignal = {"external": tsExternalInput}

        # - Make sure layers are in sync with netowrk
        self._check_sync(bVerbose=False)

        # - Iterate over evolution order and evolve layers
        for lyr in self.lEvolOrder:

            # - Determine input for current layer
            if lyr.bExternalInput:
                # External input
                tsCurrentInput = tsExternalInput
                strIn = "external input"
            elif lyr.lyrIn is not None:
                # Output of current layer's input layer
                tsCurrentInput = dtsSignal[lyr.lyrIn.strName]
                strIn = lyr.lyrIn.strName + "'s output"
            else:
                # No input
                tsCurrentInput = None
                strIn = "nothing"

            if bVerbose:
                print("Evolving layer `{}` with {} as input".format(lyr.strName, strIn))

            # - Evolve layer and store output in dtsSignal
            dtsSignal[lyr.strName] = lyr.evolve(tsCurrentInput, tDuration)

            # - Set name for time series, if not already set
            if dtsSignal[lyr.strName].strName is None:
                dtsSignal[lyr.strName].strName = lyr.strName


        # - Update network time
        self._t += tDuration

        # - Make sure layers are still in sync with netowrk
        self._check_sync(bVerbose=False)

        # - Return dict with layer outputs
        return dtsSignal

    def train(
        self,
        fhTraining: Callable,
        tsExternalInput: TimeSeries = None,
        tDuration: float = None,
        tDurBatch: float = None,
        bVerbose=True,
        bHighVerbosity=False,
    ):
        """
        train - Train the network batch-wise by evolving the layers and
                calling fhTraining.

        :param fhTraining:      Function that is called after each evolution
                fhTraining(netObj, dtsSignals, bFirst, bFinal)
                :param netObj:      Network the network object to be trained
                :param dtsSignals:  Dictionary containing all signals in the current evolution batch
                :param bFirst:      bool Is this the first batch?
                :param bFinal:      bool Is this the final batch?

        :param tsExternalInput: TimeSeries with external input to network
        :param tDuration:       float - Duration over which netŵork should
                                        be evolved. If None, evolution is
                                        over the duration of tsExternalInput
        :param tDurBatch:       float - Duration of one batch
        :param bVerbose:        bool  - Print info about training progress
        :param bHighVerbosity:  bool  - Print info about layer evolution
                                        (only has effect if bVerbose is True)
        """

        # - Determine duration of training
        if tDuration is None:
            assert (
                tsExternalInput is not None
            ), "One of `tsExternalInput` or `tDuration` must be supplied"

            if tsExternalInput.bPeriodic:
                # - Use duration of periodic TimeSeries, if possible
                tRemaining = tsExternalInput.tDuration

            else:
                # - Evolve until the end of the input TimeSeries
                tRemaining = tsExternalInput.tStop - self.t
                assert tRemaining > 0, (
                    "Cannot determine an appropriate evolution duration. "
                    + "`tsExternalInput` finishes before the current evolution time."
                )
        else:
            tRemaining = tDuration

        # - Determine batch duration and number
        tDurBatch = tRemaining if tDurBatch is None else tDurBatch
        nNumBatches = int(np.ceil(tRemaining / tDurBatch))

        # - Iterate over batches
        bFirst = True
        bFinal = False
        for nBatch in range(1, nNumBatches + 1):
            if bVerbose:
                print(
                    "Training batch {} of {}   ".format(nBatch, nNumBatches), end="\r"
                )
            # - Evolve network
            dtsSignal = self.evolve(
                tsExternalInput,
                min(tDurBatch, tRemaining),
                bVerbose=(bHighVerbosity and bVerbose),
            )
            # - Remaining simulation time
            tRemaining -= tDurBatch
            # - Determine if this batch was the first or the last of training
            if nBatch == nNumBatches:
                bFinal = True
            # - Call the callback
            fhTraining(self, dtsSignal, bFirst, bFinal)
            bFirst = False

        if bVerbose:
            print("\nTraining successful\n")

    def stream(
        self,
        tsExternalInput: TimeSeries = None,
        tDuration: float = None,
        fhCallback: Callable = None,
        tCallbackStep: float = None,
    ):
        """
        stream - Evolve layers in turn, single time steps

        :param tsExternalInput:
        :param tDuration:
        :param fhCallback:
        :param tCallbackStep:
        :return:
        """
        # - Call
        pass

    def _check_sync(self, bVerbose: bool = True) -> bool:
        """
        _check_sync - Check whether the time t of all layers matches self.t
                     If not, throw an exception.
        """
        bSync = True
        if bVerbose:
            print("Network time is {}. \n\t Layer times:".format(self.t))
            print(
                "\n".join(
                    (
                        "\t\t {}: {}".format(lyr.strName, lyr.t)
                        for lyr in self.lEvolOrder
                    )
                )
            )
        for lyr in self.lEvolOrder:
            if abs(lyr.t - self.t) >= fTolRel * self.t + fTolAbs:
                bSync = False
                print(
                    "\t WARNING: Layer `{}` is not in sync (t={})".format(
                        lyr.strName, lyr.t
                    )
                )
        if bSync:
            if bVerbose:
                print("\t All layers are in sync with network.")
        else:
            raise NetworkError("Not all layers are in sync with the network.")
        return bSync

    def reset_time(self):
        """
        reset_time() - Reset the time of the network to zero. Does not reset state.
        """
        # - Reset time for each layer
        for lyr in self.setLayers:
            lyr.reset_time()

        # - Reset global network time
        self._t = 0

    def reset_state(self):
        """
        reset_state() - Reset the state of the network. Does not reset time.
        """
        # - Reset state for each layer
        for lyr in self.setLayers:
            lyr.reset_state()

    def reset_all(self):
        """
        reset_all() - Reset state and time of the network.
        """
        for lyr in self.setLayers:
            lyr.reset_all()

        # - Reset global network time
        self._t = 0

    def __repr__(self):
        return (
            "{} object with {} layers\n".format(
                self.__class__.__name__, len(self.setLayers)
            )
            + "    "
            + "\n    ".join([str(lyr) for lyr in self.setLayers])
        )

    @property
    def t(self):
        return self._t

    # @fDt.setter
    # def fDt(self, fNewDt):
    #     self.__fDt = fNewDt
    #     for lyr in self.setLayers:
    #         lyr.fDt = self.__fDt


### --- NetworkError exception class
class NetworkError(Exception):
    pass