"""
Low level DynapSE1 simulator.
Solves the characteristic equations to simulate the circuits.
Trainable parameters

References:
[1] E. Chicca, F. Stefanini, C. Bartolozzi and G. Indiveri,
    "Neuromorphic Electronic Circuits for Building Autonomous Cognitive Systems,"
    in Proceedings of the IEEE, vol. 102, no. 9, pp. 1367-1388, Sept. 2014,
    doi: 10.1109/JPROC.2014.2313954.

[2] C. Bartolozzi and G. Indiveri, “Synaptic dynamics in analog vlsi,” Neural
    Comput., vol. 19, no. 10, p. 2581–2603, Oct. 2007. [Online]. Available:
    https://doi.org/10.1162/neco.2007.19.10.2581

[3] Dynap-SE1 Neuromorphic Chip Simulator for NICE Workshop 2021
    https://code.ini.uzh.ch/yigit/NICE-workshop-2021

[4] Course: Neurormophic Engineering 1
    Tobi Delbruck, Shih-Chii Liu, Giacomo Indiveri
    https://tube.switch.ch/channels/88df64b6

[5] Course: 21FS INI508 Neuromorphic Intelligence
    Giacomo Indiveri
    https://tube.switch.ch/switchcast/uzh.ch/series/5ee1d666-25d2-4c4d-aeb9-4b754b880345?order=newest-first


Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
13/07/2021
"""

import numpy as onp

from rockpool.nn.modules.jax.jax_module import JaxModule
from rockpool.parameters import Parameter, State, SimulationParameter


import jax
import jax.random as rand
from jax.lax import scan
from jax import numpy as np

from dataclasses import dataclass

from typing import (
    Dict,
    Union,
    List,
    Optional,
    Tuple,
    Any,
    Callable,
)

from rockpool.typehints import (
    JP_ndarray,
    P_float,
    FloatVector,
)

from rockpool.devices.dynapse.utils import (
    get_param_vector,
    set_param,
)

from rockpool.devices.dynapse.dynapse1_simconfig import (
    DynapSE1SimulationConfiguration,
    SynapseParameters,
    MembraneParameters,
    FeedbackParameters,
)


DynapSE1State = Tuple[JP_ndarray, JP_ndarray, JP_ndarray, Optional[Any]]


@jax.custom_gradient
def step_pwl(
    Imem: FloatVector, Ispkthr: FloatVector, Ireset: FloatVector
) -> Tuple[FloatVector, Callable[[FloatVector], FloatVector]]:
    """
    step_pwl implements heaviside step function with piece-wise linear derivative to use as spike-generation surrogate

    :param x: Input current to be compared for firing
    :type x: FloatVector
    :param Ispkthr: Spiking threshold current in Amperes
    :type Ispkthr: FloatVector
    :param Ireset: Reset current after spike generation in Amperes
    :type Ireset: FloatVector
    :return: spike output value and gradient function
    :rtype: Tuple[FloatVector, Callable[[FloatVector], FloatVector]]
    """

    spikes = np.clip(np.floor(Imem - Ispkthr) + 1.0, 0.0)
    grad_func = lambda g: (g * (Imem > Ireset) * (Ispkthr - Ireset), 0.0, 0.0)
    return spikes, grad_func


class DynapSE1NeuronSynapseJax(JaxModule):
    """
    Solves the chip dynamical equations for the DPI neuron and synapse models.
    Receives configuration as bias currents and solves membrane and synapse dynamics using ``jax`` backend.
    One block has
        - 4 synapses receiving spikes from the other circuits,
        - 1 recurrent synapse for spike frequency adaptation,
        - 1 membrane evaluating the state and deciding fire or not

    For all the synapses, the ``DPI Synapse`` update equations below are solved in parallel.

    :DPI Synapse:

    .. math ::

        I_{syn}(t_1) = \\begin{cases} I_{syn}(t_0) \\cdot exp \\left( \\dfrac{-dt}{\\tau} \\right) &\\text{in any case} \\\\ \\\\ I_{syn}(t_1) + \\dfrac{I_{th} I_{w}}{I_{\\tau}} \\cdot \\left( 1 - exp \\left( \\dfrac{-t_{pulse}}{\\tau} \\right) \\right) &\\text{if a spike arrives} \\end{cases}

    Where

    .. math ::

        \\tau = \\dfrac{C U_{T}}{\\kappa I_{\\tau}}

    For the membrane update, the forward Euler solution below is applied.

    :Membrane:

    .. math ::

        dI_{mem} = \dfrac{I_{mem}}{\tau \left( I_{mem} + I_{th} \right) } \cdot \left( I_{mem_{\infty}} + f(I_{mem}) - I_{mem} \left( 1 + \dfrac{I_{ahp}}{I_{\tau}} \right) \right) \cdot dt

        I_{mem}(t_1) = I_{mem}(t_0) + dI_{mem}

    Where

    .. math ::

        I_{mem_{\\infty}} = \\dfrac{I_{th}}{I_{\\tau}} \\left( I_{in} - I_{ahp} - I_{\\tau}\\right)

        f(I_{mem}) = \\dfrac{I_{a}}{I_{\\tau}} \\left(I_{mem} + I_{th} \\right )

        I_{a} = \\dfrac{I_{a_{gain}}}{1+ exp\\left(-\\dfrac{I_{mem}+I_{a_{th}}}{I_{a_{norm}}}\\right)}

    :On spiking:

    When the membrane potential for neuron :math:`j`, :math:`I_{mem, j}` exceeds the threshold current :math:`I_{spkthr}`, then the neuron emits a spike.

    .. math ::

        I_{mem, j} > I_{spkthr} \\rightarrow S_{j} = 1

        I_{mem, j} = I_{reset}

    :Attributes:

    :attr biases: name list of all the low level biases
    :type biases: List[str]

    :Parameters:

    :param shape: The number of neruons to employ, defaults to None
    :type shape: tuple, optional
    :param sim_config: Dynap-SE1 bias currents and simulation configuration parameters, defaults to None
    :type sim_config: Optional[DynapSE1SimulationConfiguration], optional
    :param w_in: Initial input weights defining the connections from virtual FPGA neurons to real device neurons. It must be a rectangular matrix with shape ``(Nin, Nrec, 4)``. The last 4 holds a weight matrix for 4 different synapse types.
    :type w_in: Optional[FloatVector], optional

        #  Gb Ga N  A
         [[0, 0, 0, 1], # pre = 0 (virtual) post = 0 (device)
          [0, 0, 0, 1],  #                  post = 1 (device)
          [0, 0, 0, 0],  #                  post = 2 (device)
          [0, 0, 0, 0],  #                  post = 3 (device)
          [0, 0, 0, 1]], #                  post = 4 (device)

         [[0, 0, 0, 0], # pre = 1 (virtual)
          [0, 0, 0, 0],
          [0, 0, 1, 0],
          [0, 0, 1, 0],
          [0, 0, 0, 1]],

         [[0, 0, 0, 0], # pre = 3 (virtual)
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 1, 0, 0]]],

        Virtual(External Input)

            AMPA : 1 from n5 to n0, 1 from n5 to n1 1 from n5 to n4
            NMDA : 1 from n6 to n2, 1 from n6 to n3 1 from n6 to n4
            GABA_A: 1 from n7 to n4

    :param w_rec: If the module is initialised in recurrent mode, one can provide a concrete initialisation for the recurrent weights, which must be a square matrix with shape ``(Nrec, Nrec, 4)``. The last 4 holds a weight matrix for 4 different synapse types. If the model is not initialised in recurrent mode, then you may not provide ``w_rec``.
    :type w_rec: Optional[FloatVector], optional

        Let's say 5 device neuron and 3 virtual FPGA neurons initiated with w_rec

        #  Gb Ga N  A
        [[[0, 0, 0, 0],  # pre = 0 (device) post = 0 (device)
          [0, 0, 0, 1],  #                  post = 1 (device)
          [0, 0, 0, 0],  #                  post = 2 (device)
          [0, 0, 0, 0],  #                  post = 3 (device)
          [0, 1, 0, 0]], #                  post = 4 (device)

         [[0, 0, 0, 0], # pre = 1 (device)
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 0]],

         [[2, 0, 0, 0], # pre = 2 (device)
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 1],
          [0, 0, 0, 0]],

         [[0, 0, 0, 0], # pre = 3 (device)
          [0, 0, 0, 0],
          [0, 0, 0, 1],
          [0, 0, 0, 0],
          [0, 0, 0, 0]],

         [[0, 0, 0, 0], # pre = 4 (device)
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 1, 0]],

        Real
            AMPA : 1 from n0 to n1, 1 from n2 to n3, 1 from n3 to n2
            NMDA : 1 from n4 to n4
            GABA_A: 1 from n0 to n4
            GABA_B: 2 from n2 to n0

    :param dt: The time step for the forward-Euler ODE solver, defaults to 1e-3
    :type dt: float, optional
    :param rng_key: The Jax RNG seed to use on initialisation. By default, a new seed is generated, defaults to None
    :type rng_key: Optional[Any], optional
    :param spiking_input: Whether this module receives spiking input, defaults to True
    :type spiking_input: bool, optional
    :param spiking_output: Whether this module produces spiking output, defaults to True
    :type spiking_output: bool, optional
    :raises ValueError: When the user does not provide a valid shape

    :Instance Variables:

    :ivar SYN: A dictionary storing default indexes(order) of the synapse types
    :type SYN: Dict[str, int]
    :ivar target_idx: The indexes to rearange the default ordered array [GABA_B, GABA_A, NMDA, AMPA, AHP] into custom order [...]
    :type target_idx: np.ndarray
    :ivar default_idx: The indexes to rearange the custom ordered array [...] into default order [GABA_B, GABA_A, NMDA, AMPA, AHP]
    :type default_idx: np.ndarray
    :ivar Imem: Array of membrane currents of the neurons with shape = (Nrec,)
    :type Imem: JP_ndarray
    :ivar Itau_mem: Array of membrane leakage currents of the neurons with shape = (Nrec,)
    :type Itau_mem: JP_ndarray
    :ivar f_gain_mem: Array of membrane gain parameter of the neurons with shape = (Nrec,)
    :type f_gain_mem: JP_ndarray
    :ivar mem_fb: positive feedback circuit heuristic parameters:Ia_gain, Ia_th, and Ia_norm
    :type mem_fb: FeedbackParameters
    :ivar Isyn: 2D array of synapse currents of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA, AHP] with shape = (5,Nrec)
    :type Isyn: JP_ndarray
    :ivar Itau_syn: 2D array of synapse leakage currents of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA, AHP] with shape = (5,Nrec)
    :type Itau_syn: JP_ndarray
    :ivar f_gain_syn: 2D array of synapse gain parameters of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA, AHP] with shape = (5,Nrec)
    :type gain_syn: JP_ndarray
    :ivar Iw: 2D array of synapse weight currents of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA, AHP] with shape = (5,Nrec)
    :type Iw: JP_ndarray
    :ivar spikes: Logical spiking raster for each neuron at the last simulation time-step with shape (Nrec,)
    :type spikes: JP_ndarray
    :ivar Io: Dark current in Amperes that flows through the transistors even at the idle state
    :type Io: float
    :ivar Ispkthr: Spiking threshold current in with shape (Nrec,)
    :type Ispkthr: JP_ndarray
    :ivar Ireset: Reset current after spike generation with shape (Nrec,)
    :type Ireset: JP_ndarray
    :ivar f_tau_mem: Tau factor for membrane circuit. :math:`f_{\\tau} = \\dfrac{U_T}{\\kappa \\cdot C}`, :math:`f_{\\tau} = I_{\\tau} \\cdot \\tau`
    :type f_tau_mem: float
    :ivar f_tau_syn: A vector of tau factors in the following order: [GABA_B, GABA_A, NMDA, AMPA, AHP]
    :type f_tau_syn: np.ndarray
    :ivar f_t_ref: The factor of conversion from refractory period in seconds to refractory period bias current in Amperes
    :type f_t_ref: float
    :ivar f_t_pulse: The factor of conversion from pulse width in seconds to pulse width bias current in Amperes
    :type f_t_pulse: float
    :ivar t_pulse: the width of the pulse in seconds produced by virtue of a spike
    :type t_pulse: float
    :ivar t_pulse_ahp: reduced pulse width also look at ``t_pulse`` and ``fpulse_ahp``
    :type t_pulse_ahp: float
    :ivar Idc: Constant DC current in Amperes, injected to membrane
    :type Idc: float
    :ivar If_nmda: The NMDA gate current in Amperes setting the NMDA gating voltage. If :math:`V_{mem} > V_{nmda}` : The :math:`I_{syn_{NMDA}}` current is added up to the input current, else it cannot
    :type If_nmda: float
    :ivar t_ref: refractory period in seconds, limits maximum firing rate
    :type t_ref: float
    :ivar timer_ref: timer to keep the time from the spike generation until the refractory period ends
    :type timer_ref: int


    [] TODO: ATTENTION Now, the implementation is only for one core, extend it for multiple cores
    [] TODO: think about activating and deactivating certain circuit blocks.
    [] TODO: all neurons cannot have the same parameters ideally however, they experience different parameters in practice because of device mismatch
    [] TODO: What is the initial configuration of biases?
    [] TODO: How to convert from bias current parameters to high-level parameters and vice versa?
    [] TODO: Provides mismatch simulation (as second step)
        -As a utility function that operates on a set of parameters?
        -As a method on the class?
    """

    syn_types = ["GABA_B", "GABA_A", "NMDA", "AMPA", "AHP"]
    SYN = dict(zip(syn_types, range(len(syn_types))))

    def __init__(
        self,
        shape: tuple = None,
        sim_config: Optional[DynapSE1SimulationConfiguration] = None,
        w_in: Optional[FloatVector] = None,
        w_rec: Optional[FloatVector] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = True,
        spiking_output: bool = True,
        *args,
        **kwargs,
    ) -> None:
        """
        __init__ Initialize ``DynapSE1NeuronSynapseJax`` module. Parameters are explained in the class docstring.
        """

        # Check the parameters and initialize to default if necessary
        if shape is None:
            raise ValueError("You must provide a ``shape`` tuple (N,) or (N,N)")

        if rng_key is None:
            rng_key = rand.PRNGKey(onp.random.randint(0, 2 ** 63))

        if sim_config is None:
            sim_config = DynapSE1SimulationConfiguration()

        _, rng_key = rand.split(np.array(rng_key, dtype=np.uint32))
        self._rng_key: JP_ndarray = State(rng_key, init_func=lambda _: rng_key)

        super().__init__(
            shape=shape,
            spiking_input=spiking_input,
            spiking_output=spiking_output,
            *args,
            **kwargs,
        )

        # Check the network size and initialize the input and recurrent weight vector accordingly
        self.w_in, self.w_rec = self._init_weights(w_in, w_rec)

        # --- Parameters & States --- #
        self.Imem, self.Itau_mem, self.f_gain_mem, self.mem_fb = self._set_mem_params(
            init=sim_config.mem,
        )

        ## Synapse parameters are combined in the order of [GABA_B, GABA_A, NMDA, AMPA, AHP]
        self.Isyn, self.Itau_syn, self.f_gain_syn, self.Iw = self._set_syn_params(
            gaba_b=sim_config.gaba_b,
            gaba_a=sim_config.gaba_a,
            nmda=sim_config.nmda,
            ampa=sim_config.ampa,
            ahp=sim_config.ahp,
        )
        self.spikes: JP_ndarray = State(shape=(self.size_out,), init_func=np.zeros)

        # --- Simulation Parameters --- #
        self.dt: P_float = SimulationParameter(dt)

        ## Layout Params
        self.Io = SimulationParameter(sim_config.layout.Io)

        ## Configuration Parameters
        self.f_tau_mem = SimulationParameter(sim_config.f_tau_mem)
        self.f_tau_syn = SimulationParameter(sim_config.f_tau_syn)
        self.f_t_ref = SimulationParameter(sim_config.f_t_ref)
        self.f_t_pulse = SimulationParameter(sim_config.f_t_pulse)
        self.t_pulse = SimulationParameter(sim_config.t_pulse)
        self.t_pulse_ahp = SimulationParameter(sim_config.t_pulse_ahp)
        self.Idc = SimulationParameter(sim_config.Idc)
        self.If_nmda = SimulationParameter(sim_config.If_nmda)
        self.t_ref = SimulationParameter(sim_config.t_ref)

        ### Refractory Period
        self.timer_ref = State(shape=(self.size_out,), init_func=np.zeros)

        ### Policy currents
        self.Ispkthr: JP_ndarray = SimulationParameter(
            shape=(self.size_out,),
            family="simulation",
            init_func=lambda s: np.ones(s) * sim_config.Ispkthr,
        )
        self.Ireset: JP_ndarray = SimulationParameter(
            shape=(self.size_out,),
            family="simulation",
            init_func=lambda s: np.ones(s) * sim_config.Ireset,
        )

    def evolve(
        self, input_data: np.ndarray, record: bool = True
    ) -> Tuple[np.ndarray, dict, dict]:
        """
        evolve implements raw JAX evolution function for a DynapSE1NeuronSynapseJax module.
        The function solves the dynamical equations introduced at the ``DynapSE1NeuronSynapseJax`` module definition

        :param input_data: Input array of shape ``(T, Nrec)`` to evolve over. Represents number of spikes at that timebin
        :type input_data: np.ndarray
        :param record: record the each timestep of evolution or not, defaults to False
        :type record: bool, optional
        :return: outputs, states, record_dict
            :outputs: is an array with shape ``(T, Nout)`` containing the output data(spike raster) produced by this module.
            :states: is a dictionary containing the updated module state following evolution.
            :record_dict: is a dictionary containing the recorded state variables during the evolution at each time step, if the ``record`` argument is ``True``.
        :rtype: Tuple[np.ndarray, dict, dict]
        """

        def forward(
            state: DynapSE1State, spike_inputs_ts: np.ndarray
        ) -> Tuple[DynapSE1State, Tuple[JP_ndarray, JP_ndarray, JP_ndarray]]:
            """
            forward implements single time-step neuron and synapse dynamics

            :param state: (spikes, Imem, Isyn, key)
                spikes: Logical spike raster for each neuron [Nrec]
                Imem: Membrane currents of each neuron [Nrec]
                Isyn: Synapse currents of each synapses[GABA_B, GABA_A, NMDA, AMPA, AHP] of each neuron [5xNrec]
                key: The Jax RNG seed to be used for mismatch simulation
            :type state: DynapSE1State
            :param spike_inputs_ts: incoming spike raster to be used as an axis [T, Nrec]
            :type spike_inputs_ts: np.ndarray
            :return: state, (spikes, Imem, Isyn)
                state: Updated state at end of the forward steps
                spikes: Logical spiking raster for each neuron over time [Nrec]
                Imem: Updated membrane membrane currents of each neuron [Nrec]
                Isyn: Updated synapse currents of each synapses[GABA_B, GABA_A, NMDA, AMPA, AHP] of each neuron [5xNrec]
            :rtype: Tuple[DynapSE1State, Tuple[JP_ndarray, JP_ndarray, JP_ndarray]]
            """
            # [] TODO : Would you allow currents to go below Io or not?!!!!

            spikes, Imem, Isyn, key, timer_ref = state

            # Reset Imem depending on spiking activity
            Imem = (1 - spikes) * Imem + spikes * self.Ireset

            # Set the refractrory timer
            timer_ref -= self.dt
            timer_ref = np.clip(timer_ref, 0)
            timer_ref = (1 - spikes) * timer_ref + spikes * self.t_ref

            ## ATTENTION : Optimization can make Itau_mem and I_tau_syn < Io
            # We might have division by 0 if we allow this to happen!
            Itau_mem_clip = np.clip(self.Itau_mem, self.Io)
            Itau_syn_clip = np.clip(self.Itau_syn, self.Io)

            # --- Implicit parameters  --- #  # 5xNrec
            tau_mem = self.f_tau_mem / Itau_mem_clip
            tau_syn = (self.f_tau_syn / Itau_syn_clip.T).T
            Isyn_inf = self.f_gain_syn * self.Iw

            # --- Forward step: DPI SYNAPSES --- #
            ## spike input for 4 synapses: GABA_B, GABA_A, NMDA, AMPA; spike output for 1 synapse: AHP
            ## w_in.shape = NinxNrecx4 [pre,post,syn]
            ## w_rec.shape = NrecxNrecx4 [pre,post,syn]

            spikes_external = np.dot(self.w_in.T, spike_inputs_ts)
            spikes_internal = np.dot(self.w_rec.T, spikes)
            spike_inputs = np.add(spikes_external, spikes_internal) + self.Io

            ## Calculate the effective pulse width with a linear increase
            t_pw_in = self.t_pulse * spike_inputs  # 4xNrec [GABA_B, GABA_A, NMDA, AMPA]
            t_pw_out = self.t_pulse_ahp * spikes  # 1xNrec [AHP]
            t_pw = np.vstack((t_pw_in, t_pw_out))

            ## Exponential charge and discharge factor arrays
            f_charge = 1 - np.exp(-t_pw / tau_syn)  # 5xNrec
            f_discharge = np.exp(-self.dt / tau_syn)  # 5xNrec

            ## DISCHARGE in any case
            Isyn = f_discharge * Isyn

            ## CHARGE if spike occurs -- UNDERSAMPLED -- dt >> t_pulse
            Isyn += f_charge * Isyn_inf
            Isyn = np.clip(Isyn, self.Io)  # 5xNrec

            # --- Forward step: MEMBRANE --- #

            ## Decouple synaptic currents and calculate membrane input
            Igaba_b, Igaba_a, Inmda, Iampa, Iahp = Isyn

            # Inmda = 0 if Vmem < Vth_nmda else Inmda
            I_nmda_dp = Inmda / (1 + self.If_nmda / Imem)

            # Iin = 0 if the neuron is in the refractory period
            Iin = I_nmda_dp + Iampa - Igaba_b + self.Idc
            Iin *= np.logical_not(timer_ref.astype(bool))
            Iin = np.clip(Iin, self.Io)

            ## Steady state current
            Imem_inf = self.f_gain_mem * (Iin - (Iahp + Igaba_a) - Itau_mem_clip)
            Ith_mem_clip = self.f_gain_mem * Itau_mem_clip

            ## Positive feedback
            Ia = self.mem_fb.Igain / (
                1 + np.exp(-(Imem - self.mem_fb.Ith) / self.mem_fb.Inorm)
            )
            Ia = np.clip(Ia, self.Io)
            f_Imem = ((Ia) / (Itau_mem_clip)) * (Imem + Ith_mem_clip)

            ## Forward Euler Update
            del_Imem = (Imem / (tau_mem * (Ith_mem_clip + Imem))) * (
                Imem_inf + f_Imem - (Imem * (1 + ((Iahp + Igaba_a) / Itau_mem_clip)))
            )
            Imem = Imem + del_Imem * self.dt
            Imem = np.clip(Imem, self.Io)

            # --- Spike Generation Logic --- #
            ## Detect next spikes (with custom gradient)
            spikes = step_pwl(Imem, self.Ispkthr, self.Ireset)

            state = (spikes, Imem, Isyn, key, timer_ref)
            return state, (spikes, Imem, Isyn)

        # --- Evolve over spiking inputs --- #
        state, (spikes_ts, Imem_ts, Isyn_ts) = scan(
            forward,
            (self.spikes, self.Imem, self.Isyn, self._rng_key, self.timer_ref),
            input_data,
        )

        new_spikes, new_Imem, new_Isyn, new_rng_key, new_timer_ref = state

        # --- RETURN ARGUMENTS --- #
        outputs = spikes_ts

        ## the state returned should be in the same shape with the state dictionary given
        states = {
            "_rng_key": new_rng_key,
            "Imem": new_Imem,
            "Isyn": new_Isyn,
            "spikes": new_spikes,
            "timer_ref": new_timer_ref,
        }

        record_dict = {
            "input_data": input_data,
            "spikes": spikes_ts,
            "Imem": Imem_ts,
            "Igaba_b": Isyn_ts[:, self.SYN["GABA_B"], :],
            "Igaba_a": Isyn_ts[:, self.SYN["GABA_A"], :],
            "Inmda": Isyn_ts[:, self.SYN["NMDA"], :],
            "Iampa": Isyn_ts[:, self.SYN["AMPA"], :],
            "Iahp": Isyn_ts[:, self.SYN["AHP"], :],
        }

        return outputs, states, record_dict

    def _set_syn_params(
        self,
        gaba_b: Optional[SynapseParameters] = None,
        gaba_a: Optional[SynapseParameters] = None,
        nmda: Optional[SynapseParameters] = None,
        ampa: Optional[SynapseParameters] = None,
        ahp: Optional[SynapseParameters] = None,
    ) -> Tuple[JP_ndarray, JP_ndarray, JP_ndarray, JP_ndarray]:
        """
        _set_syn_params helps constructing and initiating synapse parameters and states for ["AHP", "NMDA", "AMPA", "GABA_A", "GABA_B"]

        :param gaba_b: GABA_B (shunt) synapse paramters (Isyn, Itau, f_gain, Iw), defaults to None
        :type gaba_b: Optional[SynapseParameters], optional
        :param gaba_a: GABA_A synapse paramters (Isyn, Itau, f_gain, Iw), defaults to None
        :type gaba_a: Optional[SynapseParameters], optional
        :param nmda: NMDA synapse paramters (Isyn, Itau, f_gain, Iw), defaults to None
        :type nmda: Optional[SynapseParameters], optional
        :param ampa: AMPA synapse paramters (Isyn, Itau, f_gain, Iw), defaults to None
        :type ampa: Optional[SynapseParameters], optional
        :param ahp: Spike frequency adaptation block parameters (Isyn, Itau, f_gain, Iw), defaults to None
        :type ahp: Optional[SynapseParameters], optional

        :return: Isyn, Itau, f_gain, Iw : states and parameters in the order of [GABA_B, GABA_A, NMDA, AMPA, AHP] with shape = (5,Nrec)
            Isyn: 2D array of synapse currents (State)
            Itau: 2D array of synapse leakage currents (Parameter)
            f_gain: 2D array of synapse gain parameters (SimulationParameter)
            Iw: 2D array of synapse weight currents (Parameter)
        :rtype: Tuple[JP_ndarray, JP_ndarray, JP_ndarray, JP_ndarray]
        """

        dpi_list = [None] * len(self.SYN)

        dpi_list[self.SYN["GABA_B"]] = gaba_b
        dpi_list[self.SYN["GABA_A"]] = gaba_a
        dpi_list[self.SYN["NMDA"]] = nmda
        dpi_list[self.SYN["AMPA"]] = ampa
        dpi_list[self.SYN["AHP"]] = ahp

        def get_dpi_parameter(
            target: str, family: str, object: Optional[str] = "parameter"
        ) -> JP_ndarray:
            """
            get_dpi_parameter encapsulates required data management to set a synaptic parameter

            :param target: target parameter to be extracted from the DPIParameters object: Isyn, Itau, f_gain, or Iw
            :type target: str
            :param family: the parameter family name
            :type family: str
            :param object: the object type to be constructed. It can be "state", "parameter" or "simulation"
            :type object: Optional[str], optional
            :return: constructed parameter or the state variable
            :rtype: JP_ndarray
            """
            _Iparam = get_param_vector(dpi_list, target)
            shape = (len(_Iparam), self.size_out)
            init_func = lambda s: (np.ones(s).T * _Iparam).T
            Iparam = set_param(shape, family, init_func, object)

            return Iparam

        # Construct the parameter objects
        Isyn = get_dpi_parameter("Isyn", "synapse", object="state")
        Itau = get_dpi_parameter("Itau", "leak")
        Iw = get_dpi_parameter("Iw", "weight")
        f_gain = get_dpi_parameter("f_gain", "gain")
        return Isyn, Itau, f_gain, Iw

    def _set_mem_params(
        self, init: MembraneParameters, family: Optional[str] = "membrane"
    ) -> Tuple[JP_ndarray, JP_ndarray, JP_ndarray, FeedbackParameters]:
        """
        _set_mem_params constructs and initiates membrane parameters and states

        :param init: Inital membrane block parameters (Imem, Itau, f_gain, feedback(Igain, Ith, Inorm))
        :type init: MembraneParameters
        :param family: the parameter family name, defaults to "membrane"
        :type family: Optional[str], optional
        :return: Imem, Itau, f_gain, feedback
            Imem: Array of membrane currents with shape = (Nrec,) (State)
            Itau: Array of membrane leakage currents with shape = (Nrec,) (Parameter)
            f_gain: Array of membrane gain parameters with shape = (Nrec,) (SimulationParameter)
            feedback: positive feedback circuit heuristic parameters: Ia_gain, Ia_th, and Ia_norm
        :rtype: Tuple[JP_ndarray, JP_ndarray, JP_ndarray, FeedbackParameters]
        """

        def get_mem_parameter(
            target: str, object: Optional[str] = "parameter"
        ) -> JP_ndarray:
            """
            get_mem_parameter encapsulates required data management for setting a membrane parameter

            :param target: target parameter to be extracted from the MembraneParameters object: Imem, Itau, or f_gain
            :type target: str
            :param object: the object type to be constructed. It can be "state", "parameter" or "simulation"
            :type object: Optional[str], optional
            :return: constructed parameter or the state variable
            :rtype: JP_ndarray
            """

            shape = (self.size_out,)
            init_func = lambda s: np.ones(s) * init.__getattribute__(target)
            Iparam = set_param(shape, family, init_func, object)
            return Iparam

        Imem = get_mem_parameter("Imem", object="state")
        Itau = get_mem_parameter("Itau")
        f_gain = get_mem_parameter("f_gain")
        feedback: FeedbackParameters = init.feedback

        return Imem, Itau, f_gain, feedback

    def _init_weights(
        self,
        w_in: Optional[FloatVector] = None,
        w_rec: Optional[FloatVector] = None,
    ) -> Union[JP_ndarray, float]:
        """
        _init_w_rec Intialize a recurrent weight matrix parameter given the network shape.

        :param w_in: Initial input weights defining the connections from virtual FPGA neurons to real device neurons. It must be a rectangular matrix with shape ``(Nin, Nrec, 4)``. The last 4 holds a weight matrix for 4 different synapse types.
        :type w_in: Optional[FloatVector], optional
        :param w_rec: If the module is initialised in recurrent mode, one can provide a concrete initialisation for the recurrent weights, which must be a square matrix with shape ``(Nrec, Nrec, 4)``. The last 4 holds a weight matrix for 4 different synapse types. If the model is not initialised in recurrent mode, then you may not provide ``w_rec``.
        :type w_rec: Optional[FloatVector], optional
        :raises ValueError: If `shape` is unidimensional, then `w_rec` may not be provided as an argument.
        :raises ValueError: `shape` may not specify more than two dimensions (Nin, Nrec).
        :return: Recurrent weight matrix parameter initialized randomly or depending on an initial weight vector.
        :rtype: Union[JP_ndarray, float]
        """

        def get_weight_matrix(
            weight_matrix: Optional[FloatVector], shape: Tuple[int]
        ) -> JP_ndarray:
            """
            get_weight_matrix Create a weight matrix parameter for w_in or w_rec given a shape.

            :param weight_matrix: initial matrix values. init_func runs to fill the matrix if None.
            :type weight_matrix: Optional[FloatVector]
            :param shape: A tuple (or list) specifying the permitted shape of the attribute. If not provided, the shape of the concrete initialisation data will be used as the attribute shape.
            :type shape: Tuple[int]
            :return: a trainable weight matrix
            :rtype: JP_ndarray

            [] TODO: More realistic, sparse weight matrix initialization. Make multiple connections possible in the initialization with non-uniform selection
            """
            weight_init = lambda s: rand.randint(
                rand.split(self._rng_key)[0],
                shape=shape,
                minval=0,
                maxval=2,
            )

            # Values between 0,64
            weight_matrix: JP_ndarray = Parameter(
                weight_matrix,
                family="weight",
                init_func=weight_init,
                shape=shape,
            )

            return weight_matrix

        if w_in is not None:
            w_in = np.array(w_in, dtype=np.float32)

        # Feed forward Mode
        if len(self.shape) == 1:
            # - Feed-forward mode
            if w_rec is not None:
                raise ValueError(
                    "If `shape` is unidimensional, then `w_rec` may not be provided as an argument."
                )

            w_rec = np.zeros((self.size_out, self.size_out, 4))

        # Recurrent mode
        else:
            if len(self.shape) > 2:
                raise ValueError(
                    "`shape` can not specify more than two dimensions (Nin, Nrec)."
                )

            if w_rec is not None:
                w_rec = np.array(w_rec, dtype=np.float32)

            w_rec = get_weight_matrix(w_rec, (self.size_out, self.size_out, 4))

        w_in = get_weight_matrix(w_in, (self.size_in, self.size_out, 4))

        return w_in, w_rec

    ## --- HIGH LEVEL TIME CONSTANTS -- ##

    @property
    def tau_mem(self):
        """
        tau_mem holds an array of time constants in seconds for neurons with shape = (Nrec,)

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_mem / self.Itau_mem.T

    @property
    def tau_syn(self):
        """
        tau_syn holds an array of time constants in seconds for each synapse of the neurons with shape = (Nrec,5)
        There are tau_ahp, tau_nmda, tau_ampa, tau_gaba_a, and tau_gaba_b methods as well to fetch the time constants of the exact synapse

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_syn / self.Itau_syn.T

    @property
    def tau_gaba_b(self):
        """
        tau_gaba_b holds an array of time constants in seconds for GABA_B synapse of the neurons with shape = (Nrec,)

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_syn[self.SYN["GABA_B"]] / self.Itau_syn[self.SYN["GABA_B"]]

    @property
    def tau_gaba_a(self):
        """
        tau_gaba_a holds an array of time constants in seconds for GABA_A synapse of the neurons with shape = (Nrec,)

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_syn[self.SYN["GABA_A"]] / self.Itau_syn[self.SYN["GABA_A"]]

    @property
    def tau_nmda(self):
        """
        tau_nmda holds an array of time constants in seconds for NMDA synapse of the neurons with shape = (Nrec,)

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_syn[self.SYN["NMDA"]] / self.Itau_syn[self.SYN["NMDA"]]

    @property
    def tau_ampa(self):
        """
        tau_ampa holds an array of time constants in seconds for AMPA synapse of the neurons with shape = (Nrec,)

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_syn[self.SYN["AMPA"]] / self.Itau_syn[self.SYN["AMPA"]]

    @property
    def tau_ahp(self):
        """
        tau_ahp holds an array of time constants in seconds for AHP synapse of the neurons with shape = (Nrec,)

        :return: array of time constants
        :rtype: JP_ndarray
        """
        return self.f_tau_syn[self.SYN["AHP"]] / self.Itau_syn[self.SYN["AHP"]]

    ## --- MID-LEVEL HIDDEN BIAS CURRENTS (JAX) -- ##

    @property
    def Ith_mem(self):
        return self.Itau_mem * self.f_gain_mem

    @property
    def Ith_syn(self):
        return self.Itau_syn * self.f_gain_syn
