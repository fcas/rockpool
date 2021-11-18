def test_exp_quantization():
    import numpy as np
    import torch
    import copy
    from rockpool.transform.quantize_methods import global_quantize, channel_quantize
    # from rockpool.nn.modules.torch import TorchModule
    # from rockpool.nn.modules import LIFJax, LinearJax, JaxModule
    from rockpool.nn.combinators import Sequential, Residual
    from rockpool.nn.modules.torch import TorchModule, LinearTorch, LIFTorch, LIFBitshiftTorch
    from rockpool.devices.xylo import mapper
    from rockpool.devices.xylo import config_from_specification
    from rockpool.devices.xylo import XyloCim
    # from rockpool.graph import *

    Nin = 16
    Nhidden = 64
    Nout = 8
    mod = Sequential(
        LinearTorch((Nin, Nhidden)),
        LIFTorch(shape=(Nhidden, Nhidden),
                 tau_syn=0.02,
                 tau_mem=0.02,
                 threshold=1,),
        LinearTorch((Nhidden, Nout)),
        LIFTorch(shape=(Nout, Nout),
                 tau_syn=0.02,
                 tau_mem=0.02,
                 threshold=1,),
    )
    submod = mod._submodule_names
    mod0 = mod.get_submodule(submod[0])
    mod2 = mod.get_submodule(submod[2])

    w_in = np.random.exponential(4, [Nin, Nhidden])
    w_in_torch = torch.tensor(w_in).float()
    mod0.weight.data = w_in_torch

    w_out = np.random.exponential(0.1, [Nhidden, Nout])
    w_out_torch = torch.tensor(w_out).float()
    mod2.weight.data = w_out_torch

    float_graph = mod.as_graph()
    float_specs = mapper(float_graph, weight_dtype="float", threshold_dtype="float", dash_dtype="float")
    dt = float_specs["dt"]
    global_specs = copy.copy(float_specs)
    channel_specs = copy.copy(float_specs)

    del float_specs["mapped_graph"]
    del float_specs["dt"]
    xylo_conf_float, is_valid, message = config_from_specification(**float_specs)
    print("Float valid config: ", is_valid, message)

    global_specs.update(global_quantize(**global_specs, fuzzy_scaling=False))
    del global_specs["mapped_graph"]
    del global_specs["dt"]
    xylo_conf_global, is_valid, message = config_from_specification(**global_specs)
    print('Global valid config: ', is_valid, message)

    channel_specs.update(channel_quantize(**channel_specs))
    del channel_specs["mapped_graph"]
    del channel_specs["dt"]
    xylo_conf_channel, is_valid, message = config_from_specification(**channel_specs)
    print('Channel valid config: ', is_valid, message)
    #
    # T = 100
    # Nin = 16
    # batch = 1
    # inp = torch.Tensor(np.random.randint(low=1, high=10, size=(batch, T, Nin)))
    #
    # output_f, _, rec_rockpool_f = Net(inp, record=True)
    #
    # cim_g = XyloCim.from_config(xylo_conf_global, dt=dt)
    # cim_g.reset_state()
    # output_g, _, rec_cim_g = cim_g(inp[0].cpu().numpy(), record=True)
    #
    # cim_c = XyloCim.from_config(xylo_conf_channel, dt=dt)
    # cim_c.reset_state()
    # output_c, _, rec_cim_c = cim_c(inp[0].cpu().numpy(), record=True)
    #
    # spk_in_f = rec_rockpool_f['rec_spk_inp'].squeeze(1).detach().numpy().astype(int)
    #
    # spk_in_g = rec_cim_g['Spikes']
    # spk_out_g = output_g
    #
    # spk_in_c = rec_cim_c['Spikes']
    # spk_out_c = output_c
    #
    # in_point = (spk_in_f.shape[0] - 1) * spk_in_f.shape[1]
    # out_point = (spk_out_f.shape[0]) * spk_out_f.shape[1]
    #
    # in_point = (spk_in_f.shape[0] - 1) * spk_in_f.shape[1]
    # out_point = (spk_out_f.shape[0]) * spk_out_f.shape[1]
    #
    # print(f'In LIF spike global match float percent: {np.sum(spk_in_f[1:] == spk_in_g[:-1]) / in_point * 100}')
    # print(f'Out LIF spike global match float percent: {np.sum(spk_out_f[1:] == spk_out_g[:-1]) / out_point * 100}')
    #
    # print(f'\nIn LIF spike channel match float percent: {np.sum(spk_in_f[1:] == spk_in_c[:-1]) / in_point * 100}')
    # print(f'Out LIF spike channel match float percent: {np.sum(spk_out_f[1:] == spk_out_c[:-1]) / out_point * 100}')
    #
    # print(f'\nIn LIF spike global match channel: {np.sum(spk_in_g[:-1] == spk_in_c[:-1]) / in_point * 100}')
    # print(f'Out LIF spike global match channel: {np.sum(spk_out_g[:-1] == spk_out_c[:-1]) / out_point * 100}')