#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates. All rights reserved.

from typing import Dict

import torch
from ml.rl.models.base import ModelBase
from ml.rl.models.categorical_dqn import CategoricalDQN
from ml.rl.models.dqn import FullyConnectedDQN
from ml.rl.models.dueling_q_network import DuelingQNetwork
from ml.rl.models.parametric_dqn import FullyConnectedParametricDQN
from ml.rl.preprocessing.normalization import (
    NormalizationParameters,
    get_num_output_features,
)
from ml.rl.thrift.core.ttypes import (
    ContinuousActionModelParameters,
    DiscreteActionModelParameters,
)
from ml.rl.training.c51_trainer import C51Trainer
from ml.rl.training.dqn_trainer import DQNTrainer
from ml.rl.training.parametric_dqn_trainer import ParametricDQNTrainer


def create_dqn_trainer_from_params(
    model: DiscreteActionModelParameters,
    normalization_parameters: Dict[int, NormalizationParameters],
    use_gpu: bool = False,
    use_all_avail_gpus: bool = False,
    metrics_to_score=None,
):
    metrics_to_score = metrics_to_score or []
    if model.rainbow.categorical:
        q_network = CategoricalDQN(
            state_dim=get_num_output_features(normalization_parameters),
            action_dim=len(model.actions),
            num_atoms=model.rainbow.num_atoms,
            qmin=model.rainbow.qmin,
            qmax=model.rainbow.qmax,
            sizes=model.training.layers[1:-1],
            activations=model.training.activations[:-1],
            dropout_ratio=model.training.dropout_ratio,
            use_gpu=use_gpu,
        )
    elif model.rainbow.dueling_architecture:
        q_network = DuelingQNetwork(  # type: ignore
            layers=[get_num_output_features(normalization_parameters)]
            + model.training.layers[1:-1]
            + [len(model.actions)],
            activations=model.training.activations,
        )
    else:
        q_network = FullyConnectedDQN(  # type: ignore
            state_dim=get_num_output_features(normalization_parameters),
            action_dim=len(model.actions),
            sizes=model.training.layers[1:-1],
            activations=model.training.activations[:-1],
            dropout_ratio=model.training.dropout_ratio,
        )

    if use_gpu and torch.cuda.is_available():
        q_network = q_network.cuda()

    q_network_target = q_network.get_target_network()

    reward_network, q_network_cpe, q_network_cpe_target = None, None, None
    if model.evaluation.calc_cpe_in_training:
        # Metrics + reward
        num_output_nodes = (len(metrics_to_score) + 1) * len(model.actions)
        reward_network = FullyConnectedDQN(
            state_dim=get_num_output_features(normalization_parameters),
            action_dim=num_output_nodes,
            sizes=model.training.layers[1:-1],
            activations=model.training.activations[:-1],
            dropout_ratio=model.training.dropout_ratio,
        )
        q_network_cpe = FullyConnectedDQN(
            state_dim=get_num_output_features(normalization_parameters),
            action_dim=num_output_nodes,
            sizes=model.training.layers[1:-1],
            activations=model.training.activations[:-1],
            dropout_ratio=model.training.dropout_ratio,
        )

        if use_gpu and torch.cuda.is_available():
            reward_network.cuda()
            q_network_cpe.cuda()

        q_network_cpe_target = q_network_cpe.get_target_network()

    if use_all_avail_gpus and not model.rainbow.categorical:
        q_network = q_network.get_distributed_data_parallel_model()
        reward_network = (
            reward_network.get_distributed_data_parallel_model()
            if reward_network
            else None
        )
        q_network_cpe = (
            q_network_cpe.get_distributed_data_parallel_model()
            if q_network_cpe
            else None
        )

    if model.rainbow.categorical:
        return C51Trainer(
            q_network,
            q_network_target,
            model,
            use_gpu,
            metrics_to_score=metrics_to_score,
        )

    else:
        return DQNTrainer(
            q_network,
            q_network_target,
            reward_network,
            model,
            use_gpu,
            q_network_cpe=q_network_cpe,
            q_network_cpe_target=q_network_cpe_target,
            metrics_to_score=metrics_to_score,
        )


def create_parametric_dqn_trainer_from_params(
    model: ContinuousActionModelParameters,
    state_normalization_parameters: Dict[int, NormalizationParameters],
    action_normalization_parameters: Dict[int, NormalizationParameters],
    use_gpu: bool = False,
    use_all_avail_gpus: bool = False,
):
    q_network = FullyConnectedParametricDQN(
        state_dim=get_num_output_features(state_normalization_parameters),
        action_dim=get_num_output_features(action_normalization_parameters),
        sizes=model.training.layers[1:-1],
        activations=model.training.activations[:-1],
    )
    reward_network = FullyConnectedParametricDQN(
        state_dim=get_num_output_features(state_normalization_parameters),
        action_dim=get_num_output_features(action_normalization_parameters),
        sizes=model.training.layers[1:-1],
        activations=model.training.activations[:-1],
    )
    q_network_target = q_network.get_target_network()

    if use_gpu and torch.cuda.is_available():
        q_network = q_network.cuda()
        q_network_target = q_network_target.cuda()
        reward_network = reward_network.cuda()

    if use_all_avail_gpus:
        q_network = q_network.get_distributed_data_parallel_model()
        q_network_target = q_network_target.get_distributed_data_parallel_model()
        reward_network = reward_network.get_distributed_data_parallel_model()

    return ParametricDQNTrainer(
        q_network, q_network_target, reward_network, model, use_gpu
    )
