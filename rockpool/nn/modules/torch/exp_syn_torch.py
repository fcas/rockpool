"""
Implement a exponential synapse module, using a Torch backend
"""

from importlib import util

if util.find_spec("torch") is None:
    raise ModuleNotFoundError(
        "'Torch' backend not found. Modules that rely on Torch will not be available."
    )

from typing import Optional, Tuple, Any, Union
import numpy as np
from rockpool.nn.modules.torch.torch_module import TorchModule
import torch
import rockpool.parameters as rp

import rockpool.typehints as rt

__all__ = ["ExpSynTorch"]


class ExpSynTorch(TorchModule):
    """
    An exponential synapse model

    This module implements the update equations:

    .. math ::

        I_{syn} += S_{in}(t) + \sigma \zeta_t
        I_{syn} *= \exp(-dt / \tau)

        where :math:`S_{in}(t)` is a vector containing ``1`` or weighted spike for each input channel that emits a spike at time :math:`t`, :math:`\\tau` is the vector of time constants for each synapse, and :math:`\sigma` is the std. dev of a Wiener process after 1s.
    """

    def __init__(
        self,
        shape: Union[tuple, int],
        tau: rt.FloatVector = None,
        noise_std: float = 0.0,
        dt: float = 1e-3,
        *args,
        **kwargs,
    ):
        """
        Instantiate an exp. synapse module

        Args:
            shape (tuple): Number of synapses that will be created. Example: shape = (5,).
            tau (np.ndarray): An optional array with concrete initialisation data for the synaptic time constants, in seconds. If not provided, an individual trainable time-constant of 10ms will be used by default.
            noise_std (float): The std. dev. after 1s of the noise Wiener process added to each synapse.
            dt (float): The time step for the forward-Euler ODE solver, in seconds. Default: 1ms
        """
        # Initialize super class
        super().__init__(
            shape=shape, spiking_input=True, spiking_output=False, *args, **kwargs,
        )

        # - To-float-tensor conversion utility
        to_float_tensor = lambda x: torch.tensor(x).float()

        # - Initialise tau
        self.tau_syn: rt.P_tensor = rp.Parameter(
            tau,
            shape=[(self.size_out,), ()],
            family="taus",
            init_func=lambda s: torch.ones(*s) * 10e-3,
            cast_fn=to_float_tensor,
        )
        """ (torch.Tensor) Time constants of each synapse in seconds ``(N,)`` or ``()`` """

        # - Initialise noise std dev
        self.noise_std: rt.P_tensor = rp.SimulationParameter(
            noise_std, cast_fn=to_float_tensor
        )
        """ (float) Noise std. dev after 1 second """

        # - Initialise state
        self.isyn: rt.P_tensor = rp.State(
            shape=(self.size_out,), init_func=lambda s: torch.zeros(*s),
        )
        """ (torch.tensor) Synaptic current state for each synapse ``(1, N)`` """

        # - Store dt
        self.dt: rt.P_float = rp.SimulationParameter(dt)
        """ (float) Simulation time-step in seconds """

    def evolve(
        self, input_data: torch.Tensor, record: bool = False
    ) -> Tuple[Any, Any, Any]:

        # - Evolve the module
        output_data, states, _ = super().evolve(input_data, record)

        # - Build a record dictionary
        record_dict = {"isyn": self._isyn_rec} if record else {}

        # - Return the result of evolution
        return output_data, states, record_dict

    def forward(self, data: torch.Tensor) -> torch.Tensor:
        """
        Forward method for processing data through this layer
        Adds synaptic inputs to the synaptic states and mimics the exponential synapse dynamics

        Parameters
        ----------
        data: Tensor
            Data takes the shape of (batch, time_steps, N)

        Returns
        -------
        out: Tensor
            Out of spikes with the shape (batch, time_steps, N)
        """
        print(data.shape)
        # - Auto-batch over input data
        data, (isyn,) = self._auto_batch(data, (self.isyn,))
        n_batches, time_steps, _ = data.shape
        print(data.shape)
        print(n_batches, time_steps)
        print(self.isyn.shape, isyn.shape)

        # - Build a tensor to compute and return internal state
        self._isyn_rec = torch.zeros(data.shape, device=data.device)

        # - Compute decay factor
        beta = torch.exp(-self.dt / self.tau_syn)
        noise_zeta = self.noise_std * torch.sqrt(torch.tensor(self.dt))

        # - Loop over time
        for t in range(time_steps):
            isyn += data[:, t, :] + noise_zeta * torch.randn(
                isyn.shape, device=isyn.device
            )
            isyn *= beta
            self._isyn_rec[:, t, :] = isyn

        # - Store the final state
        self.isyn = isyn[0].detach()

        # - Return the evolved synaptic current
        return self._isyn_rec
