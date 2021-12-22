"""
Low level DynapSE simulator.
Solves the characteristic equations to simulate the circuits.
Trainable parameters

renamed: dynapse1_neuron_synapse_jax.py -> adexplif_jax.py @ 211206

References:
[1] E. Chicca, F. Stefanini, C. Bartolozzi and G. Indiveri,
    "Neuromorphic Electronic Circuits for Building Autonomous Cognitive Systems,"
    in Proceedings of the IEEE, vol. 102, no. 9, pp. 1367-1388, Sept. 2014,
    doi: 10.1109/JPROC.2014.2313954.

[2] C. Bartolozzi and G. Indiveri, “Synaptic dynamics in analog vlsi,” Neural
    Comput., vol. 19, no. 10, p. 2581–2603, Oct. 2007. [Online]. Available:
    https://doi.org/10.1162/neco.2007.19.10.2581

[3] P. Livi and G. Indiveri, “A current-mode conductance-based silicon neuron for
    address-event neuromorphic systems,” in 2009 IEEE International Symposium on
    Circuits and Systems, May 2009, pp. 2898–2901

[4] Dynap-SE1 Neuromorphic Chip Simulator for NICE Workshop 2021
    https://code.ini.uzh.ch/yigit/NICE-workshop-2021

[5] Course: Neurormophic Engineering 1
    Tobi Delbruck, Shih-Chii Liu, Giacomo Indiveri
    https://tube.switch.ch/channels/88df64b6

[6] Course: 21FS INI508 Neuromorphic Intelligence
    Giacomo Indiveri
    https://tube.switch.ch/switchcast/uzh.ch/series/5ee1d666-25d2-4c4d-aeb9-4b754b880345?order=newest-first


Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
13/07/2021
"""

import numpy as onp
import logging

import jax
import jax.random as rand

from jax.lax import scan
from jax import numpy as np

from typing import (
    Union,
    Optional,
    Tuple,
    Any,
    Callable,
    List,
    Dict,
)

from rockpool.typehints import (
    JP_ndarray,
    FloatVector,
)

from rockpool.nn.modules.jax.jax_module import JaxModule
from rockpool.parameters import Parameter, State, SimulationParameter
from rockpool.devices.dynapse.simconfig import DynapSE1SimBoard, DynapSE1SimCore
from rockpool.devices.dynapse.dynapse import DynapSE

DynapSEState = Tuple[
    JP_ndarray, JP_ndarray, JP_ndarray, JP_ndarray, JP_ndarray, Optional[Any]
]
DynapSERecord = Tuple[JP_ndarray, JP_ndarray, JP_ndarray, JP_ndarray, JP_ndarray]


def poisson_weight_matrix(
    shape: Tuple[int], fill_rate: Union[float, List[float]] = [0.04, 0.06, 0.2, 0.2]
) -> np.ndarray:
    """
    poisson_weight_matrix creates a 3D weight matrix using a poisson distribution
    The function takes desired fill rates of the matrices and converts it to a poisson lambda.
    The analytical solution is here:

    .. math ::
        f(X=x) = \\dfrac{\\lambda^{x}\\cdot e^{-\\lambda}}{x!}
        f(X=0) = e^{-\\lambda}
        p = 1 - f(X=0) = 1 - e^{-\\lambda}
        e^{-\\lambda} = 1-p
        \\lambda = -ln(1-p) ; 0<p<1

    :param shape: the 3D shape of the weight matrix
    :type shape: Tuple[int]
    :param fill_rate: the fill rates desired to be converted to a list of posisson rates of the weights specific to synaptic-gates (3rd dimension)
    :type lambda_list: Union[float, List[float]]
    :raises ValueError: The possion rate list given does not have the same shape with the 3rd dimension
    :return: 3D numpy array representing a Dynap-SE connectivity matrix
    :rtype: np.ndarray
    """
    if isinstance(fill_rate, float):
        fill_rate = [fill_rate] * shape[2]

    if len(fill_rate) != shape[2]:
        raise ValueError(
            "The possion rate list given does not have the same shape with the 3rd dimension"
        )

    lambda_list = -onp.log(1 - onp.array(fill_rate))

    # First create a base weight matrix
    columns = []
    for l in lambda_list:
        w = onp.random.poisson(l, (*shape[0:2], 1))
        columns.append(w)

    weight = onp.concatenate(columns, axis=2, dtype=onp.float32)
    return weight


def dynapse_weights(
    shape: Tuple[int],
    log_range: Tuple[float] = (-12.0, -6.0),
    fill_rate: Union[float, List[float]] = [0.04, 0.06, 0.2, 0.2],
) -> np.ndarray:
    """
    dynapse_weights generates a random weight current matrix defining the connection strengths between
    neurons inside a network. The values represented inside the matrix are the current values in Amperes
    and the log range is the range of power of 10s allowed for this current to have.
    The function takes desired fill rates of the matrices and converts it to a poisson lambda.
    The analytical solution is here:

    .. math ::
        f(X=x) = \\dfrac{\\lambda^{x}\\cdot e^{-\\lambda}}{x!}
        f(X=0) = e^{-\\lambda}
        p = 1 - f(X=0) = 1 - e^{-\\lambda}
        e^{-\\lambda} = 1-p
        \\lambda = -ln(1-p) ; 0<p<1

    :param shape: the 3D shape of the weight matrix
    :type shape: Tuple[int]
    :param log_range: the uniform range of power of 10s for the current values to fill the weight matrix, defaults to (-12.0, -5.0)
    :type log_range: Tuple[float], optional
    :param fill_rate: the fill rates desired to be converted to a list of posisson rates of the weights specific to synaptic-gates (3rd dimension)
    :type fill_rate: Union[float, List[float]]
    :raises ValueError: The possion rate list given does not have the same shape with the 3rd dimension
    :return: 3D numpy array representing a Dynap-SE connectivity matrix
    :rtype: np.ndarray
    """

    if isinstance(fill_rate, float):
        fill_rate = [fill_rate] * shape[2]

    if len(fill_rate) != shape[2]:
        raise ValueError(
            "The possion rate list given does not have the same shape with the 3rd dimension"
        )

    # Power Matrix
    mean = onp.sum(log_range) / 2
    sigma = (log_range[1] - log_range[0]) / 5  # 5 sigma -> 99.7%
    power = onp.random.normal(mean, sigma, shape)

    # Create a mask using poisson process, with fill rate is different for each synapse type
    lambda_list = -onp.log(1 - onp.array(fill_rate))
    columns = []
    for l in lambda_list:
        w = onp.random.poisson(l, (*shape[0:2], 1))
        columns.append(w)

    # convert this into a boolean array
    mask = onp.concatenate(columns, axis=2).astype(bool)

    # dense matrix
    base = onp.full(shape, 10.0)
    weight = onp.float_power(base, power) * mask
    return weight.astype(onp.float32)


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


class DynapSEAdExpLIFJax(JaxModule, DynapSE):
    """
    DynapSEAdExpLIFJax solves dynamical chip equations for the DPI neuron and synapse models.
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

    :param shape: Either a single dimension ``N``, which defines a feed-forward layer of DynapSE AdExpIF neurons, or two dimensions ``(N, N)``, which defines a recurrent layer of DynapSE AdExpIF neurons.
    :type shape: Optional[Tuple], optional
    :param sim_config: Dynap-SE1 bias currents and simulation configuration parameters, defaults to None
    :type sim_config: Optional[Union[DynapSE1SimCore, DynapSE1SimBoard]], optional
    :param has_rec: When ``True`` the module provides a trainable recurrent weight matrix. ``False``, module is feed-forward, defaults to True
    :type has_rec: bool, optional
    :param w_rec: If the module is initialised in recurrent mode, one can provide a concrete initialisation for the recurrent weights, which must be a square matrix with shape ``(Nrec, Nrec, 4)``. The last 4 holds a weight matrix for 4 different synapse types. If the model is not initialised in recurrent mode, then you may not provide ``w_rec``.
    :type w_rec: Optional[FloatVector], optional

        Let's say 5 neurons allocated

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
            GABA_B: 2 from n2 to n0
            GABA_A: 1 from n0 to n4
            NMDA : 1 from n4 to n4
            AMPA : 1 from n0 to n1, 1 from n2 to n3, 1 from n3 to n2

    :param dt: The time step for the forward-Euler ODE solver, defaults to 1e-3
    :type dt: float, optional
    :param rng_key: The Jax RNG seed to use on initialisation. By default, a new seed is generated, defaults to None
    :type rng_key: Optional[Any], optional
    :param spiking_input: Whether this module receives spiking input, defaults to True
    :type spiking_input: bool, optional
    :param spiking_output: Whether this module produces spiking output, defaults to True
    :type spiking_output: bool, optional

    :raises ValueError: ``shape`` should be defined (N*4,N,)!
    :raises ValueError: The simulation configuration object size and number of device neruons does not match!
    :raises ValueError: If ``has_rec`` is False, then `w_rec` may not be provided as an argument or initialized by the module
    :raises ValueError: `shape[0]` should be `shape[1]`*4 in the recurrent mode

    :Instance Variables:

    :ivar SYN: A dictionary storing default indexes(order) of the synapse types
    :type SYN: Dict[str, int]
    :ivar Isyn: 2D array of synapse currents of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA] with shape (4,Nrec)
    :type Isyn: JP_ndarray
    :ivar Iahp: Array of spike frequency adaptation currents of the neurons with shape (Nrec,)
    :type Iahp: JP_ndarray
    :ivar Imem: Array of membrane currents of the neurons with shape (Nrec,)
    :type Imem: JP_ndarray
    :ivar spikes: Logical spiking raster for each neuron at the last simulation time-step with shape (Nrec,)
    :type spikes: JP_ndarray
    :ivar timer_ref: timer to keep the time from the spike generation until the refractory period ends
    :type timer_ref: int
    :ivar Itau_syn: 2D array of synapse leakage currents of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA] with shape (4,Nrec)
    :type Itau_syn: JP_ndarray
    :ivar Itau_ahp: Array of spike frequency adaptation leakage currents of the neurons with shape (Nrec,)
    :type Itau_ahp: JP_ndarray

    :ivar Itau_mem: Array of membrane leakage currents of the neurons with shape (Nrec,)
    :type Itau_mem: JP_ndarray
    :ivar f_gain_syn: 2D array of synapse gain parameters of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA] with shape (4,Nrec)
    :type f_gain_syn: JP_ndarray
    :ivar f_gain_ahp: Array of spike frequency adaptation gain parameters of the neurons with shape (Nrec,)
    :type f_gain_ahp: JP_ndarray
    :ivar f_gain_mem: Array of membrane gain parameter of the neurons with shape (Nrec,)
    :type f_gain_mem: JP_ndarray
    :ivar Iw: 2D array of synapse weight currents of the neurons in the order of [GABA_B, GABA_A, NMDA, AMPA] with shape (4,Nrec)
    :type Iw: JP_ndarray
    :ivar Iw_ahp: Array of spike frequency adaptation weight currents of the neurons with shape (Nrec,)
    :type Iw_ahp: JP_ndarray
    :ivar Idc: Array of constant DC current in Amperes, injected to membrane with shape (Nrec,)
    :type Idc: JP_ndarray
    :ivar If_nmda: Array of the NMDA gate current in Amperes setting the NMDA gating voltage. If :math:`V_{mem} > V_{nmda}` : The :math:`I_{syn_{NMDA}}` current is added up to the input current, else it cannot with shape (Nrec,)
    :type If_nmda: JP_ndarray
    :ivar kappa: Array of mean subthreshold slope factor of the transistors with shape (Nrec,)
    :type kappa: JP_ndarray
    :ivar Ut: Array of thermal voltage in Volts with shape (Nrec,)
    :type Ut: JP_ndarray
    :ivar Io: Array of Dark current in Amperes that flows through the transistors even at the idle state with shape (Nrec,)
    :type Io: JP_ndarray
    :ivar f_tau_syn: Array of tau factors in the following order: [GABA_B, GABA_A, NMDA, AMPA] with shape (4,Nrec)
    :type f_tau_syn: np.ndarray
    :ivar f_tau_ahp: Array of tau factor for spike frequency adaptation circuit with shape (Nrec,)
    :type f_tau_ahp: JP_ndarray
    :ivar f_tau_mem: Array of tau factor for membrane circuit. :math:`f_{\\tau} = \\dfrac{U_T}{\\kappa \\cdot C}`, :math:`f_{\\tau} = I_{\\tau} \\cdot \\tau` with shape (Nrec,)
    :type f_tau_mem: JP_ndarray
    :ivar t_pulse: Array of the width of the pulse in seconds produced by virtue of a spike with shape (Nrec,)
    :type t_pulse: JP_ndarray
    :ivar t_pulse_ahp: Array of reduced pulse width also look at ``t_pulse`` and ``fpulse_ahp`` with shape (Nrec,)
    :type t_pulse_ahp: JP_ndarray
    :ivar t_ref: Array of refractory periods in seconds, limits maximum firing rate. In the refractory period the synaptic input current of the membrane is the dark current. with shape (Nrec,)
    :type t_ref: JP_ndarray
    :ivar Ispkthr: Array of spiking threshold current in with shape (Nrec,)
    :type Ispkthr: JP_ndarray
    :ivar Ireset: Array of reset current after spike generation with shape (Nrec,)
    :type Ireset: JP_ndarray

    [] TODO: parametric fill rate, different initialization methods
    [] TODO: all neurons cannot have the same parameters ideally however, they experience different parameters in practice because of device mismatch
    [] TODO: Provides mismatch simulation (as second step)
        -As a utility function that operates on a set of parameters?
        -As a method on the class?
    """

    __doc__ += "\nJaxModule" + JaxModule.__doc__

    syn_types = ["GABA_B", "GABA_A", "NMDA", "AMPA"]
    SYN = dict(zip(syn_types, range(len(syn_types))))

    def __init__(
        self,
        shape: Optional[Tuple] = None,
        sim_config: Optional[Union[DynapSE1SimCore, DynapSE1SimBoard]] = None,
        has_rec: bool = True,
        w_rec: Optional[FloatVector] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = False,
        spiking_output: bool = True,
        *args,
        **kwargs,
    ) -> None:
        """
        __init__ Initialize ``DynapSEAdExpLIFJax`` module. Parameters are explained in the class docstring.
        """

        # Check the parameters and initialize to default if necessary
        if shape is None or len(shape) != 2:
            raise ValueError(f"shape should be defined (N*4,N,)! shape={shape}")

        # Check the network size and the recurrent weight vector accordingly
        syn_size_check = lambda s: s == (s // 4) * 4  # 4 synapse per neuron for sure

        # Check if input dimension meets the 4 synapse per neuron criteria
        if not syn_size_check(shape[0]):
            raise ValueError(
                f"Input dimension ({shape[0]},..) should have been multiples of 4! (Go for {shape[0]//4}, {(shape[0]+4)//4}, or {shape[0]*4}) \n"
                f"Each neuron holds 4 synaptic state, which means 4 input gates per neuron!\n"
                f"i.e. ({(shape[0]//4)*4},..) means {shape[0]//4} neurons with 4 synapses\n"
                f"i.e. ({((shape[0]+4)//4)*4},..) means {(shape[0]+4)//4} neurons with 4 synapses\n"
                f"i.e. ({shape[0]*4},..) means {shape[0]} neurons with 4 synapses\n"
            )

        # Check if output dimension meets the 4 synapse per neuron criteria
        if shape[1] != shape[0] // 4:
            raise ValueError("`shape[0]` should be `shape[1]`*4")

        if rng_key is None:
            rng_key = rand.PRNGKey(onp.random.randint(0, 2 ** 63))

        _, rng_key = rand.split(np.array(rng_key, dtype=np.uint32))

        super(DynapSEAdExpLIFJax, self).__init__(
            shape=shape,
            spiking_input=spiking_input,
            spiking_output=spiking_output,
            *args,
            **kwargs,
        )

        if sim_config is None:
            sim_config = DynapSE1SimCore(size=self.size_out)

        if len(sim_config) != self.size_out:
            raise ValueError(
                f"The simulation configuration object size {len(sim_config)} and number of device neruons {self.size_out} does not match!"
            )

        # --- Parameters & States --- #
        init_current = lambda s: np.full(s, sim_config.Io)

        # --- States --- #

        self.spikes = State(init_func=np.zeros, shape=(self.size_out,))
        self.Isyn = State(
            sim_config.Isyn, init_func=init_current, shape=(self.size_out, 4)
        )
        self.Iahp = State(
            sim_config.Iahp, init_func=init_current, shape=(self.size_out,)
        )

        self.Imem = State(
            sim_config.Imem, init_func=init_current, shape=(self.size_out,)
        )

        self.Vmem = State(init_func=np.zeros, shape=(self.size_out,))
        self.timer_ref = State(init_func=np.zeros, shape=(self.size_out,))
        self._rng_key: JP_ndarray = State(rng_key, init_func=lambda _: rng_key)

        ## Feed forward Mode
        if not has_rec:
            if w_rec is not None:
                raise ValueError(
                    "If ``has_rec`` is False, then `w_rec` may not be provided as an argument or initialized by the module."
                )

            # In order not to make the jax complain about w_rec
            self.w_rec = np.zeros((self.size_out, self.size_in // 4, 4))
            logging.info(f"Module allocates {self.size_out} neurons with 4 synapses")

        ## Recurrent mode
        else:
            if w_rec is not None:
                w_rec = np.array(w_rec, dtype=np.float32)

            weight_init = lambda s: poisson_weight_matrix(s)

            # Values between 0,64
            self.w_rec: JP_ndarray = Parameter(
                w_rec,
                family="weights",
                init_func=weight_init,
                shape=(self.size_out, self.size_in // 4, 4),
            )
            logging.info(f"Module allocates {self.size_out} neurons with 4 synapses")

        # --- Parameters --- #
        ## Synapse
        self.Itau_syn = Parameter(sim_config.Itau_syn, shape=(self.size_out, 4))
        self.f_gain_syn = Parameter(sim_config.f_gain_syn, shape=(self.size_out, 4))

        ## Spike Frequency Adaptation
        self.Itau_ahp = Parameter(sim_config.Itau_ahp, shape=(self.size_out,))
        self.f_gain_ahp = Parameter(sim_config.f_gain_ahp, shape=(self.size_out,))
        self.Iw_ahp = Parameter(sim_config.Iw_ahp, shape=(self.size_out,))

        ## Membrane
        self.Itau_mem = Parameter(sim_config.Itau_mem, shape=(self.size_out,))
        self.Itau2_mem = Parameter(sim_config.Itau2_mem, shape=(self.size_out,))
        self.f_gain_mem = Parameter(sim_config.f_gain_mem, shape=(self.size_out,))
        self.Idc = Parameter(sim_config.Idc, shape=(self.size_out,))
        self.If_nmda = Parameter(sim_config.If_nmda, shape=(self.size_out,))

        # --- Simulation Parameters --- #
        self.dt = SimulationParameter(dt, shape=())
        self.kappa = SimulationParameter(sim_config.kappa, shape=(self.size_out,))
        self.Ut = SimulationParameter(sim_config.Ut, shape=(self.size_out,))
        self.Io = SimulationParameter(sim_config.Io, shape=(self.size_out,))

        ## Time -> Current conversion
        self.f_tau_syn = SimulationParameter(
            sim_config.f_tau_syn, shape=(self.size_out, 4)
        )
        self.f_tau_ahp = SimulationParameter(
            sim_config.f_tau_ahp, shape=(self.size_out,)
        )
        self.f_tau_mem = SimulationParameter(
            sim_config.f_tau_mem, shape=(self.size_out,)
        )
        # Pulse width
        self.t_pulse = SimulationParameter(sim_config.t_pulse, shape=(self.size_out,))
        self.t_pulse_ahp = SimulationParameter(
            sim_config.t_pulse_ahp, shape=(self.size_out,)
        )

        ## Refractory Period
        self.t_ref = SimulationParameter(sim_config.t_ref, shape=(self.size_out,))

        ## Policy
        self.Ispkthr = SimulationParameter(sim_config.Ispkthr, shape=(self.size_out,))
        self.Ireset = SimulationParameter(sim_config.Ireset, shape=(self.size_out,))

    def evolve(
        self, input_data: np.ndarray, record: bool = True
    ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        evolve implements raw JAX evolution function for a DynapSEAdExpLIFJax module.
        The function solves the dynamical equations introduced at the ``DynapSEAdExpLIFJax`` module definition

        :param input_data: Input array of shape ``(T, Nrec, 4)`` to evolve over. Represents number of spikes at that timebin for different synaptic gates
        :type input_data: np.ndarray
        :param record: record the each timestep of evolution or not, defaults to False
        :type record: bool, optional
        :return: spikes_ts, states, record_dict
            :spikes_ts: is an array with shape ``(T, Nrec)`` containing the output data(spike raster) produced by the module.
            :states: is a dictionary containing the updated module state following evolution.
            :record_dict: is a dictionary containing the recorded state variables during the evolution at each time step, if the ``record`` argument is ``True`` else empty dictionary {}
        :rtype: Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]
        """

        # --- Stateless Parameters --- #

        ## --- Synapses --- ## Nrec, 4
        Itau_syn_clip = np.clip(self.Itau_syn.T, self.Io).T
        Ith_syn_clip = self.f_gain_syn * Itau_syn_clip

        ## --- Spike frequency adaptation --- ## Nrec
        Itau_ahp_clip = np.clip(self.Itau_ahp, self.Io)
        Ith_ahp_clip = self.f_gain_ahp * Itau_ahp_clip

        ## -- Membrane -- ## Nrec
        Itau_mem_clip = np.clip(self.Itau_mem, self.Io)
        Ith_mem_clip = self.f_gain_mem * Itau_mem_clip

        # Both (T, Nrecx4), and (T, Nrec, 4) shaped inputs are accepted
        input_data = np.reshape(input_data, (input_data.shape[0], -1, 4))

        def forward(
            state: DynapSEState, Iw_input: np.ndarray
        ) -> Tuple[DynapSEState, DynapSERecord]:
            """
            forward implements single time-step neuron and synapse dynamics

            :param state: (spikes, Isyn, Iahp, Imem, timer_ref, key)
                spikes: Logical spike raster for each neuron [Nrec]
                Isyn: Synapse currents of each synapses[GABA_B, GABA_A, NMDA, AMPA] of each neuron [4xNrec]
                Iahp: Spike frequency adaptation currents of each neuron [Nrec]
                Imem: Membrane currents of each neuron [Nrec]
                timer_ref: Refractory timer of each neruon [Nrec]
                key: The Jax RNG seed to be used for mismatch simulation
            :type state: DynapSEState
            :param Iw_input: external weighted current matrix generated via input spikes [Nrec, 4]
            :type Iw_input: np.ndarray
            :return: state, (spikes, Isyn, Iahp, Imem, Vmem)
                state: Updated state at end of the forward steps
                spikes: Logical spiking raster for each neuron over time [Nrec]
                Isyn: Updated synapse currents of each synapses[GABA_B, GABA_A, NMDA, AMPA] of each neuron [4xNrec]
                Iahp: Updated spike frequency adaptation currents of each neuron [Nrec]
                Imem: Updated membrane currents of each neuron [Nrec]
                Vmem: Updated membrane potentials of each neuron [Nrec]
            :rtype: Tuple[DynapSEState, DynapSERecord]
            """
            # [] TODO : Would you allow currents to go below Io or not?!!!!

            spikes, Isyn, Iahp, Imem, Vmem, timer_ref, key = state

            # ---------------------------------- #
            # --- Forward step: DPI SYNAPSES --- #
            # ---------------------------------- #

            ## Real time weight is 0 if no spike, w_rec if spike event occurs
            Iws_internal = np.dot(self.w_rec.T, spikes).T
            Iws = np.add(Iws_internal, Iw_input)

            # Isyn_inf is the current that a synapse current would reach with a sufficiently long pulse
            Isyn_inf = (self.f_gain_syn * Iws) - Ith_syn_clip
            Isyn_inf = np.clip(Isyn_inf, 0)

            # synaptic time constant is practically much more longer than expected when Isyn << Ith
            tau_syn_prime = (self.f_tau_syn / Itau_syn_clip) * (
                1 + (Ith_syn_clip / Isyn)
            )

            ## Exponential charge, discharge positive feedback factor arrays
            f_charge = 1 - np.exp(-self.t_pulse / tau_syn_prime.T).T  # Nrecx4
            f_discharge = np.exp(-self.dt / tau_syn_prime)  # Nrecx4

            ## DISCHARGE in any case
            Isyn = f_discharge * Isyn

            ## CHARGE if spike occurs -- UNDERSAMPLED -- dt >> t_pulse
            Isyn += f_charge * Isyn_inf
            Isyn = np.clip(Isyn.T, self.Io).T  # Nrecx4

            # ---------------------------------- #
            # ---------------------------------- #
            # ---------------------------------- #

            # ------------------------------------------------------ #
            # --- Forward step: AHP : Spike Frequency Adaptation --- #
            # ------------------------------------------------------ #

            Iws_ahp = self.Iw_ahp * spikes  # 0 if no spike, Iw_ahp if spike
            Iahp_inf = (self.f_gain_ahp * Iws_ahp) - Ith_ahp_clip

            tau_ahp_prime = (self.f_tau_ahp / Itau_ahp_clip) * (
                1 + (Ith_ahp_clip / Iahp)
            )

            # Calculate charge and discharge factors
            f_charge_ahp = 1 - np.exp(-self.t_pulse_ahp / tau_ahp_prime)  # Nrec
            f_discharge_ahp = np.exp(-self.dt / tau_ahp_prime)  # Nrec

            ## DISCHARGE in any case
            Iahp = f_discharge_ahp * Iahp

            ## CHARGE if spike occurs -- UNDERSAMPLED -- dt >> t_pulse
            Iahp += f_charge_ahp * Iahp_inf
            Iahp = np.clip(Iahp, self.Io)  # Nrec

            # ------------------------------------------------------ #
            # ------------------------------------------------------ #
            # ------------------------------------------------------ #

            # ------------------------------ #
            # --- Forward step: MEMBRANE --- #
            # ------------------------------ #

            f_feedback = np.exp(
                (self.kappa ** 2 / (self.kappa + 1)) * (Vmem / self.Ut)
            )  # 4xNrec

            ## Decouple synaptic currents and calculate membrane input
            Igaba_b, Igaba_a, Inmda, Iampa = Isyn.T

            # Inmda = 0 if Vmem < Vth_nmda else Inmda
            I_nmda_dp = Inmda / (1 + self.If_nmda / Imem)

            # Iin = 0 if the neuron is in the refractory period
            Iin = I_nmda_dp + Iampa - Igaba_b + self.Idc
            Iin *= np.logical_not(timer_ref.astype(bool))
            Iin = np.clip(Iin, self.Io)

            # Igaba_a (shunting) contributes to the membrane leak instead of subtracting from Iin
            Ileak = Itau_mem_clip + Igaba_a
            tau_mem_prime = self.f_tau_mem / Ileak * (1 + (Ith_mem_clip / Imem))

            ## Steady state current
            Imem_inf = self.f_gain_mem * (Iin - Iahp - Ileak)

            ## Positive feedback
            Ifb = self.Io * f_feedback
            f_Imem = ((Ifb) / (Ileak)) * (Imem + Ith_mem_clip)

            ## Forward Euler Update
            del_Imem = (1 / tau_mem_prime) * (
                Imem_inf + f_Imem - (Imem * (1 + (Iahp / Ileak)))
            )
            Imem = Imem + del_Imem * self.dt
            Imem = np.clip(Imem, self.Io)

            ## Membrane Potential
            Vmem = (self.Ut / self.kappa) * np.log(Imem / self.Io)

            # ------------------------------ #
            # ------------------------------ #
            # ------------------------------ #

            # ------------------------------ #
            # --- Spike Generation Logic --- #
            # ------------------------------ #

            ## Detect next spikes (with custom gradient)
            spikes = step_pwl(Imem, self.Ispkthr, self.Ireset)

            ## Reset Imem depending on spiking activity
            Imem = (1 - spikes) * Imem + spikes * self.Ireset

            ## Set the refractrory timer
            timer_ref -= self.dt
            timer_ref = np.clip(timer_ref, 0)
            timer_ref = (1 - spikes) * timer_ref + spikes * self.t_ref

            # ------------------------------ #
            # ------------------------------ #
            # ------------------------------ #

            state = (spikes, Isyn, Iahp, Imem, Vmem, timer_ref, key)
            return state, (spikes, Isyn, Iahp, Imem, Vmem)

        # --- Evolve over spiking inputs --- #
        state, (spikes_ts, Isyn_ts, Iahp_ts, Imem_ts, Vmem_ts) = scan(
            forward,
            (
                self.spikes,
                self.Isyn,
                self.Iahp,
                self.Imem,
                self.Vmem,
                self.timer_ref,
                self._rng_key,
            ),
            input_data,
        )

        (
            new_spikes,
            new_Isyn,
            new_Iahp,
            new_Imem,
            new_Vmem,
            new_timer_ref,
            new_rng_key,
        ) = state

        # --- RETURN ARGUMENTS --- #

        ## the state returned should be in the same shape with the state dictionary given
        states = {
            "spikes": new_spikes,
            "Isyn": new_Isyn,
            "Iahp": new_Iahp,
            "Imem": new_Imem,
            "Vmem": new_Vmem,
            "timer_ref": new_timer_ref,
            "_rng_key": new_rng_key,
        }

        record_dict = {}
        if record:
            record_dict = {
                "Igaba_b": Isyn_ts[:, :, self.SYN["GABA_B"]],
                "Igaba_a": Isyn_ts[:, :, self.SYN["GABA_A"]],  # Shunt
                "Inmda": Isyn_ts[:, :, self.SYN["NMDA"]],
                "Iampa": Isyn_ts[:, :, self.SYN["AMPA"]],
                "Iahp": Iahp_ts,
                "Imem": Imem_ts,
                "Vmem": Vmem_ts,
            }

        return spikes_ts, states, record_dict

    @property
    def tau_mem(self) -> JP_ndarray:
        """
        tau_mem holds an array of time constants in seconds for neurons with shape = (Nrec,)
        """
        return self.f_tau_mem / self.Itau_mem

    @property
    def tau_syn(self) -> JP_ndarray:
        """
        tau_syn holds an array of time constants in seconds for each synapse of the neurons with shape = (Nrec,4)
        There are tau_gaba_b, tau_gaba_a, tau_nmda, and tau_ampa  methods as well to fetch the time constants of the exact synapse
        """
        return self.f_tau_syn / self.Itau_syn

    @property
    def tau_ahp(self) -> JP_ndarray:
        """
        tau_ahp holds an array of time constants in seconds for each spike frequency adaptation block of the neurons with shape = (Nrec,)
        """
        return self.f_tau_ahp / self.Itau_ahp

    @property
    def tau_gaba_b(self) -> JP_ndarray:
        """
        tau_gaba_b holds an array of time constants in seconds for GABA_B synapse of the neurons with shape = (Nrec,)
        """
        return self.tau_syn[self.SYN["GABA_B"]]

    @property
    def tau_gaba_a(self) -> JP_ndarray:
        """
        tau_gaba_a holds an array of time constants in seconds for GABA_A synapse of the neurons with shape = (Nrec,)
        """
        return self.tau_syn[self.SYN["GABA_A"]]

    @property
    def tau_nmda(self) -> JP_ndarray:
        """
        tau_nmda holds an array of time constants in seconds for NMDA synapse of the neurons with shape = (Nrec,)
        """
        return self.tau_syn[self.SYN["NMDA"]]

    @property
    def tau_ampa(self) -> JP_ndarray:
        """
        tau_ampa holds an array of time constants in seconds for AMPA synapse of the neurons with shape = (Nrec,)
        """
        return self.tau_syn[self.SYN["AMPA"]]

    @property
    def tau_ahp(self) -> JP_ndarray:
        """
        tau_ahp holds an array of time constants in seconds for AHP synapse of the neurons with shape = (Nrec,)
        """
        return self.tau_syn[self.SYN["AHP"]]

    ## --- MID-LEVEL HIDDEN BIAS CURRENTS (JAX) -- ##

    ### --- TAU(A.K.A LEAK) --- ###

    @property
    def Itau_gaba_b(self) -> JP_ndarray:
        """
        Itau_gaba_b holds an array of time constants bias current in Amperes for GABA_B synapse of the neurons with shape = (Nrec,)
        """
        return self.Itau_syn[self.SYN["GABA_B"]]

    @property
    def Itau_gaba_a(self) -> JP_ndarray:
        """
        Itau_gaba_a holds an array of time constants bias current in Amperes for GABA_A synapse of the neurons with shape = (Nrec,)
        """
        return self.Itau_syn[self.SYN["GABA_A"]]

    @property
    def Itau_nmda(self) -> JP_ndarray:
        """
        Itau_nmda holds an array of time constants bias current in Amperes for NMDA synapse of the neurons with shape = (Nrec,)
        """
        return self.Itau_syn[self.SYN["NMDA"]]

    @property
    def Itau_ampa(self) -> JP_ndarray:
        """
        Itau_ampa holds an array of time constants bias current in Amperes for AMPA synapse of the neurons with shape = (Nrec,)
        """
        return self.Itau_syn[self.SYN["AMPA"]]

    ### --- THRESHOLD (A.K.A GAIN) --- ###

    @property
    def Ith_mem(self) -> JP_ndarray:
        """
        Ith_mem create an array of membrane threshold(a.k.a gain) currents with shape = (Nrec,)
        """
        return self.Itau_mem * self.f_gain_mem

    @property
    def Ith_syn(self) -> JP_ndarray:
        """
        Ith_syn create an array of synaptic threshold(a.k.a gain) currents in the order of [GABA_B, GABA_A, NMDA, AMPA] with shape = (4,Nrec)
        """
        return self.Itau_syn * self.f_gain_syn

    @property
    def Ith_gaba_b(self) -> JP_ndarray:
        """
        Ith_gaba_b holds an array of gain bias current in Amperes for GABA_B synapse of the neurons with shape = (Nrec,)
        """
        return self.Ith_syn[self.SYN["GABA_B"]]

    @property
    def Ith_gaba_a(self) -> JP_ndarray:
        """
        Ith_gaba_a holds an array of gain bias current in Amperes for GABA_A synapse of the neurons with shape = (Nrec,)
        """
        return self.Ith_syn[self.SYN["GABA_A"]]

    @property
    def Ith_nmda(self) -> JP_ndarray:
        """
        Ith_nmda holds an array of gain bias current in Amperes for NMDA synapse of the neurons with shape = (Nrec,)
        """
        return self.Ith_syn[self.SYN["NMDA"]]

    @property
    def Ith_ampa(self) -> JP_ndarray:
        """
        Ith_ampa holds an array of gain bias current in Amperes for AMPA synapse of the neurons with shape = (Nrec,)
        """
        return self.Ith_syn[self.SYN["AMPA"]]
