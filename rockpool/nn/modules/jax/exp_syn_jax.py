"""
An exponential synapse layer, with a Jax backend.
"""

# - Rockpool imports
from rockpool.nn.modules import JaxModule
from rockpool.parameters import Parameter, State, SimulationParameter

# - Other imports
import jax
import jax.numpy as np
from jax.lax import scan

import numpy as onp

from typing import Union, Optional

from rockpool import typehints as rt

__all__ = ["ExpSynJax"]


class ExpSynJax(JaxModule):
    """
    Exponential synapse module with a Jax backend

    This module simulates the dynamics of a number of synapses. The synapses evolve under the dynamics

    .. math::

        I_{syn}(t+1) = \alpha \cdot I_{syn}(t) + inp(t)

        \alpha = \frac{\tau}{\textrm{dt}}

    """

    def __init__(
        self,
        shape: Union[tuple, int],
        tau: Optional[rt.FloatVector] = None,
        noise_std: float = 0.0,
        dt: float = 1e-3,
        rng_key: Optional[rt.JaxRNGKey] = None,
        spiking_input: bool = False,
        spiking_output: bool = False,
        *args,
        **kwargs,
    ):
        """
        Initialise an exponential synapse module

        Args:
            shape (Optional[tuple]): The number of units in this module ``(N,)``.
            tau (Optional[np.ndarray]): Concrete initialisation data to use for the time constants of the synapses. Default: trainable individual 10 ms for all synapses.
            dt (float): The time step for simulation, in seconds. Default: 1 ms
        """
        # - Call super-class initialisation
        super().__init__(
            shape=shape,
            spiking_input=spiking_input,
            spiking_output=spiking_output,
            *args,
            **kwargs,
        )

        # - Seed RNG
        if rng_key is None:
            rng_key = jax.random.PRNGKey(onp.random.randint(0, 2 ** 63))
        _, rng_key = jax.random.split(np.array(rng_key, dtype=np.uint32))

        # - Initialise state
        self.rng_key: Union[np.ndarray, State] = State(
            rng_key, init_func=lambda _: rng_key
        )

        # - Record parameters
        self.dt: Union[float, SimulationParameter] = SimulationParameter(dt)
        """ (float) Time step for this module """

        self.tau: rt.P_ndarray = Parameter(
            data=tau,
            shape=[(self.size_out,), ()],
            family="taus",
            init_func=lambda s: np.ones(*s) * 10e-3,
            cast_fn=np.array,
        )
        """ (np.ndarray) Time constant of each synapse """

        # - Initialise noise std dev
        self.noise_std: rt.P_float = SimulationParameter(noise_std, cast_fn=np.array)
        """ (float) Noise std. dev after 1 second """

        self.isyn: Union[np.array, State] = State(
            shape=self.size_out, init_func=np.zeros,
        )
        """ (torch.tensor) Synaptic current state for each synapse ``(1, N)`` """

    def evolve(
        self, input_data: np.array, *args, **kwargs,
    ) -> (np.ndarray, dict, dict):
        # - Get input shapes, add batch dimension if necessary
        if len(input_data.shape) == 2:
            input_data = np.expand_dims(input_data, 0)
        batches, num_timesteps, n_inputs = input_data.shape

        # - Pre-compute synapse decay beta
        beta = np.exp(-self.dt / self.tau)
        noise_zeta = self.noise_std * np.sqrt(self.dt)

        # - Define synaptic dynamics
        def forward(Isyn, input_t):
            Isyn += input_t
            Isyn *= beta
            return Isyn, Isyn

        # - Generate noise trace
        key1, subkey = jax.random.split(self.rng_key)
        noise_ts = noise_zeta * jax.random.normal(
            subkey, shape=(batches, num_timesteps, self.size_out)
        )

        # - Replicate states
        isyn = np.broadcast_to(self.isyn, (batches, self.size_in))

        # - Map over batches
        @jax.vmap
        def scan_time(isyn, input_data):
            return scan(forward, isyn, input_data)

        # - Scan over the input
        isyn, output = scan_time(isyn, input_data + noise_ts)

        # - Return output data and state
        return output, {"isyn": isyn[0]}, {}
