import numpy as np
from scipy import sparse
from typing import Callable
from brian2 import second
from matplotlib import pyplot as plt

plt.ion()

import sys 
sys.path.insert(1, '../..')

# - Local imports
from NetworksPython import TimeSeries
from NetworksPython.ecg import signal_and_target
import NetworksPython.analysis as an
import NetworksPython.network as nw

# - Layers
from NetworksPython.layers.feedforward.rate import PassThrough
from NetworksPython.layers.recurrent.iaf_brian import RecIAFBrian
from NetworksPython.layers.feedforward.exp_synapses_manual import FFExpSyn
from NetworksPython.layers.recurrent.weights import IAFSparseNet

### --- Set parameters

tDt = 0.005  # Length of time step in seconds
fHeartRate = 1  # Heart rate in rhythms per second

nTrialsTr = 3000  # Number ECG rhythms for Training
nTrialsVa = 1000  # Number ECG rhythms for validation
nRepsVa = 10  # Number repetitions of validation runs
nTrialsTe = 2000  # Number ECG rhythms for testing

nDimIn = 1  # Input dimensions
nDimOut = 9  # Output dimensions

nResSize = 512  # Reservoir size
fConnectivity = 0.4  # Percentage of non-zero recurrent weights  ##
fMeanScale = -9e-6  # Scale mean of recurrent weights  ##
fStdScale = 11e-6  # Scale standard dev. of recurrent weights  ##

tTauN = 35 * tDt  # Reservoir neuron time constant
tTauS = 350 * tDt  # Reservoir synapse time constant
tTauO = 35 * tDt  # Readout time constant

tDurBatch = 250  # Training batch duration
fRegularize = 0.001  # Regularization parameter for training with ridge regression

# Parameters concerning reservoir weights
kwResWeights = {
    "nResSize": nResSize,
    "fDensity": fConnectivity,
    "fMean" : fMeanScale / fConnectivity / nResSize,
    "fStd" : fStdScale / np.sqrt(fConnectivity),
}

# Probabilities for anomalies in ECG rhythms
pNormal = 0.8  # Probability of normal input rhythm
pAnomal = (1 - pNormal) / 6  # Probability of abnormal input rhythm

dProbs = {
    "complete_normal": pNormal,  # Normal ECG
    "complete_noP": pAnomal,  # Missing P-wave
    "complete_Pinv": pAnomal,  # Inverted P-wave
    "complete_noQRS": pAnomal,  # Missing QRS complex
    "complete_Tinv": pAnomal,  # Inverted T-wave
    "complete_STelev": pAnomal,  # Elevated ST-segment
    "complete_STdepr": pAnomal,  # Depressed ST-segment
    # "complete_tach": pAnomal,     # Tachycardia
    # "complete_brad": pAnomal,     # Bradycardia
}

# - Kwargs for signal_and_target function
kwSignal = {
    "strTargetMethod": "segment-extd",  # Method for labelling targets
    "dProbs": dProbs,
    "fHeartRate": fHeartRate,
    "tDt": tDt,
    "bVerbose": True,
    "nMinWidth": int(0.5 * fHeartRate / tDt),
    "bDetailled": True,
}


def cTrain(net: nw.Network, dtsSignal: dict, bFirst: bool, bFinal: bool):
    """
    cTrain - Train layers flOut and flOut1D with input from dtsSignal and tsTgtTr as
             target. Use fRegularize as parameter for ridge regression.
             Training may span several batches. This funciton is to be
             passed on to net and will be called after each batch.
    :param net:     Network containing the layer
    :param dtsSignal: dict with TimeSeries from network evolutions
    :param bFirst:    bool True if this is the first batch of a training
    :param bLast:    bool True if this is the final batch of a training
    """
    # - Input to flOut
    tsInput = dtsSignal["reservoir"]
    # - Infer time range of current batch
    tStart = dtsSignal["external"].tStart
    tStop = dtsSignal["external"].tStop
    # - Sample target within time range of current batch
    tsTarget1D = tsTgtTr1D.resample_within(tStart, tStop)
    tsTargetM = tsTgtTr.resample_within(tStart, tStop)
    # - Train the layer
    flOut.train_rr(tsTargetM, tsInput, fRegularize, bFirst, bFinal)
    flOut1D.train_rr(tsTarget1D, tsInput, fRegularize, bFirst, bFinal)


def ts_ecg_target(nRhythms: int, **kwargs) -> (TimeSeries, TimeSeries):
    """
    ts_ecg_target - Generate two time series, one containing an ECG signal
                   and the other the corresponding target.
    :param nRhythms:    int Number of ECG rhythms in the input
    :tDt:               float Size of a single time step
    :kwargs:            dict Kwargs that are passed on to signal_and_target
    """

    # - Input signal and target
    vfInput, mfTarget = signal_and_target(nTrials=nRhythms, **kwargs)
    vfTarget1D = mfTarget.any(axis=1)

    # - Time base
    tDt = kwargs["tDt"]
    vtTime = np.arange(0, vfInput.size * tDt, tDt)[: vfInput.size]

    # - Genrate time series
    tsInput = TimeSeries(vtTime, vfInput)
    tsTarget = TimeSeries(vtTime, mfTarget)
    tsTarget1D = TimeSeries(vtTime, vfTarget1D)

    return tsInput, tsTarget, tsTarget1D


### --- Network generation

# - Generate weight matrices
mfW_in = 2 * (np.random.rand(nDimIn, nResSize) - 0.5)
# mfW_res = RndmSparseEINet(**kwResWeights)
mfW_res = IAFSparseNet(**kwResWeights)

# - Generate layers
flIn = PassThrough(mfW=mfW_in, tDt=tDt, tDelay=0, strName="input")
rlRes = RecIAFBrian(
    mfW=mfW_res, vtTauN=tTauN, vtTauSynR=tTauS, tDt=tDt * second, strName="reservoir", fNoiseStd=0
)
flOut = FFExpSyn(
    mfW=np.zeros((nResSize, nDimOut)), tTauSyn=tTauO, tDt=tDt, strName="output"
)
flOut1D = FFExpSyn(mfW=np.zeros((nResSize, 1)), tTauSyn=tTauO, tDt=tDt, strName="output")

# - Generate network
# net = nw.Network(flIn, rlRes, flOut)
net1D = nw.Network(flIn, rlRes, flOut1D)


### --- Training
print("Training")

# - Training signal
# Generate training data and time trace
tsInTr, tsTgtTr, tsTgtTr1D = ts_ecg_target(nTrialsTr, **kwSignal)

# - Run training
net1D.train(cTrain, tsInTr, tDurBatch=tDurBatch)
net1D.reset_all()


### --- Validation run for threshold determination

print("Finding threshold")

# - Lists for storing thresholds
lfThr1D = []
lvfThrM = []

# - Validation runs
for i in range(nRepsVa):

    print("\tRun {} of {}".format(i + 1, nRepsVa), end="\r")

    # Input and target generation
    tsInVa, tsTgtVa, tsTgtVa1D = ts_ecg_target(nTrialsVa, **dict(kwSignal, bVerbose=False))

    # Simulation
    dVa1D = net1D.evolve(tsInVa, bVerbose=False)
    net1D.reset_all()
    tsOutVa = flOut.evolve(dVa1D["reservoir"], tDuration=tsInVa.tDuration)
    flOut.reset_all()

    # Threshold for 1D
    lfThr1D.append(
        an.find_threshold(
            vOutput=dVa1D["output"].mfSamples,
            vTarget=tsTgtVa1D.mfSamples.flatten(),
            nWindow=int(fHeartRate / tDt),
            nClose=int(fHeartRate / tDt),
            nAttempts=16,
            nRecursions=4,
        )
    )

    # Threshold for multi
    lvfThrM.append(
        an.find_all_thresholds_multi(
            mOutput=tsOutVa.mfSamples,
            mTarget=tsTgtVa.mfSamples,
            nWindow=int(fHeartRate / tDt),
            nClose=int(fHeartRate / tDt),
            fMin=0.1,
            nAttempts=16,
            nRecursions=4,
            bStrict=False,
        )
    )

    del dVa1D, tsOutVa

# - Average over stored thresholds

# Throw out unrealistically low thresholds
for vfT in lvfThrM:
    # Ignore thresholds < 0.1, but only consider anomalies that have
    # actually been implemented (indices 0-5)
    viIgnore, = np.where(vfT[:6, 0] < 0.1)
    vfT[viIgnore] = np.nan

vfThr = np.nanmean(lvfThrM, axis=0)
fThr1D = np.mean(list(filter(lambda x: x > 0.1, lfThr1D)))

print("Using {} as threshold for 1D output".format(fThr1D))
print("Using following thresholds for multi output:")
print(vfThr)


### --- Testing
print("Testing")
# - Test signal
# Generate test data and time trace
tsInTe, tsTgtTe, tsTgtTe1D = ts_ecg_target(nTrialsTe, **kwSignal)

# - Run test
print("1D")
dTe1D = net1D.evolve(tsInTe)
net1D.reset_all()
print("Multi")
tsOutTe = flOut.evolve(dTe1D["reservoir"], tDuration=tsInTe.tDuration)
flOut.reset_all()


# - Analysis and plotting
print("\nAnalysis of test run, multi:")
mfOutTe = tsOutTe.mfSamples
dAnalysis = an.analyze_multi(
    mfOutTe,
    tsTgtTe.mfSamples,
    tsInTe.mfSamples,
    vfThr[:, 0],
    nWindow=int(fHeartRate / tDt),
    nClose=int(fHeartRate / tDt),
    bPlot=True,
    bVerbose=True,
)
print("\nAnalysis of test run, 1D:")
vOutTe1D = dTe1D[flOut1D.strName].mfSamples
dAnalysis1D = an.analyze(
    vOutTe1D,
    tsTgtTe1D.mfSamples.flatten(),
    tsInTe.mfSamples,
    fThr1D,
    nWindow=int(fHeartRate / tDt),
    nClose=int(fHeartRate / tDt),
    bPlot=True,
    mfTarget=tsTgtTe.mfSamples,
)

# - Show statistics for individual symptom types

lstrSymptomFullNames = [
    "Inverted P-wave",
    "Missing P-wave",
    "Missing QRS-complex",
    "Inverted T-wave",
    "Elevated ST-segment",
    "Depressed ST-segment",
]

for iSymptom in dAnalysis1D["dSymptoms"].keys():
    if iSymptom < len(lstrSymptomFullNames):
        print(lstrSymptomFullNames[iSymptom] + ":")
        print(
            "1D: {:.1%}".format(dAnalysis1D["dSymptoms"][iSymptom]["fSensitivity"])
            + "\tMulti: {:.1%}\n".format(
                dAnalysis["dSymptoms"][iSymptom]["fSensitivity"]
            )
        )

np.savez(
    "multi-dim_180704.npz",
    mfW_in=mfW_in,
    mfW_res=mfW_res,
    flOutMulti=flOut,
    vfWOut1D=flOut1D.mfW,       # Cannot store objects that are part of network, store weights and bias instead
    vfBias1D=flOut1D.vfBias,
    fThr1D=fThr1D,
    vfThrMulti=vfThr[:, 0],
)
