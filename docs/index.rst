Welcome to |project|
==============================

.. raw:: html

    <img src='_static/logo_Color_perspective.png' width=80% class='main-logo' />


|project| is a Python package for working with dynamical neural network architectures, particularly for designing event-driven
networks for Neuromorphic computing hardware. |project| provides a convenient interface for designing, training
and evaluating recurrent networks, which can operate both with continuous-time dynamics and event-driven dynamics.

|project| is an open-source project managed by SynSense.

.. toctree::
   :maxdepth: 1

   about

.. toctree::
   :maxdepth: 1
   :caption: The basics

   basics/installation
   basics/introduction_to_snns.ipynb
   basics/getting_started.ipynb
   basics/time_series.ipynb
   basics/sharp_points.ipynb

.. toctree::
   :maxdepth: 1
   :caption: In depth

   in-depth/api-low-level.ipynb
   in-depth/api-high-level.ipynb
   in-depth/api-functional.ipynb
   in-depth/jax-training.ipynb
   in-depth/torch-api.ipynb
   .. in-depth/torch-training.ipynb

.. toctree::
   :maxdepth: 1
   :caption: Tutorials

   tutorials/sgd_recurrent_net.ipynb
   tutorials/jax_lif_sgd.ipynb
   tutorials/torch-training-spiking.ipynb

   tutorials/analog-frontend-example.ipynb



   .. tutorials/building_reservoir.ipynb
   .. tutorials/deneve_reservoirs.ipynb
   .. tutorials/network_ads_tutorial.ipynb

   .. tutorials/DynapseControl.ipynb
   .. tutorials/RecDynapSE.ipynb



.. toctree::
   :maxdepth: 1
   :caption: Advanced topics

   reference/api
   advanced/developers_notes
   advanced/CHANGELOG

* :ref:`genindex`
