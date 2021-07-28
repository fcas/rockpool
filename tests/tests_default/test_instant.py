import pytest


def test_imports():
    from rockpool.nn.modules import Instant, InstantJax


def test_instant():
    from rockpool.nn.modules import Instant
    import numpy as np

    # - Construct module
    N = 5
    mod = Instant(N, np.tanh)

    # - Test evolution
    T = 10
    o, ns, rs = mod(
        np.random.rand(
            T,
            N,
        )
    )
    print(o, ns, rs)


def test_instant_jax():
    from rockpool.nn.modules import InstantJax
    import numpy as np
    import jax
    import jax.numpy as jnp

    # - Construct module
    N = 5
    mod = InstantJax(N, jnp.tanh)

    # - Test evolution
    T = 10
    o, ns, rs = mod(
        np.random.rand(
            T,
            N,
        )
    )
    print(o, ns, rs)

    # - Test compiled evolution
    je = jax.jit(mod)
    o, ns, rs = je(
        np.random.rand(
            T,
            N,
        )
    )
    print(o, ns, rs)

    # - Test compiled gradient
    def loss(params, net, input, target):
        net = net.set_attributes(params)
        output, _, _ = net(input)
        return jnp.mean((output - target) ** 2)

    vgf = jax.jit(jax.value_and_grad(loss))
    l, g = vgf(
        mod.parameters(),
        mod,
        np.random.rand(
            T,
            N,
        ),
        np.random.rand(
            T,
            N,
        ),
    )
    print(l, g)