# Copyright 2020 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""Train Resnet50 on ImageNet"""

import os
import argparse

from mindspore import context
from mindspore import Tensor
from mindspore.parallel._auto_parallel_context import auto_parallel_context
from mindspore.nn.optim.momentum import Momentum
from mindspore.train.model import Model, ParallelMode
from mindspore.train.callback import ModelCheckpoint, CheckpointConfig, LossMonitor, TimeMonitor
from mindspore.train.loss_scale_manager import FixedLossScaleManager
from mindspore.train.serialization import load_checkpoint
from mindspore.train.quant import quant
from mindspore.communication.management import init
import mindspore.nn as nn
import mindspore.common.initializer as weight_init

from models.resnet_quant import resnet50_quant
from src.dataset import create_dataset
from src.lr_generator import get_lr
from src.config import quant_set, config_quant, config_noquant
from src.crossentropy import CrossEntropy
from src.utils import _load_param_into_net

parser = argparse.ArgumentParser(description='Image classification')
parser.add_argument('--run_distribute', type=bool, default=False, help='Run distribute')
parser.add_argument('--device_num', type=int, default=1, help='Device num.')
parser.add_argument('--dataset_path', type=str, default=None, help='Dataset path')
parser.add_argument('--device_target', type=str, default='Ascend', help='Device target')
parser.add_argument('--pre_trained', type=str, default=None, help='Pertained checkpoint path')
args_opt = parser.parse_args()
config = config_quant if quant_set.quantization_aware else config_noquant

if args_opt.device_target == "Ascend":
    device_id = int(os.getenv('DEVICE_ID'))
    rank_id = int(os.getenv('RANK_ID'))
    rank_size = int(os.getenv('RANK_SIZE'))
    run_distribute = rank_size > 1
    context.set_context(mode=context.GRAPH_MODE,
                        device_target="Ascend",
                        save_graphs=False,
                        device_id=device_id,
                        enable_auto_mixed_precision=True)
else:
    raise ValueError("Unsupported device target.")

if __name__ == '__main__':
    # train on ascend
    print("training args: {}".format(args_opt))
    print("training configure: {}".format(config))
    print("parallel args: rank_id {}, device_id {}, rank_size {}".format(rank_id, device_id, rank_size))
    epoch_size = config.epoch_size

    # distribute init
    if run_distribute:
        context.set_auto_parallel_context(device_num=rank_size,
                                          parallel_mode=ParallelMode.DATA_PARALLEL,
                                          parameter_broadcast=True,
                                          mirror_mean=True)
        init()
        context.set_auto_parallel_context(device_num=args_opt.device_num,
                                          parallel_mode=ParallelMode.DATA_PARALLEL,
                                          mirror_mean=True)
        auto_parallel_context().set_all_reduce_fusion_split_indices([107, 160])

    # define network
    net = resnet50_quant(class_num=config.class_num)
    net.set_train(True)

    # weight init and load checkpoint file
    if args_opt.pre_trained:
        param_dict = load_checkpoint(args_opt.pre_trained)
        _load_param_into_net(net, param_dict)
        epoch_size = config.epoch_size - config.pretrained_epoch_size
    else:
        for _, cell in net.cells_and_names():
            if isinstance(cell, nn.Conv2d):
                cell.weight.default_input = weight_init.initializer(weight_init.XavierUniform(),
                                                                    cell.weight.default_input.shape,
                                                                    cell.weight.default_input.dtype).to_tensor()
            if isinstance(cell, nn.Dense):
                cell.weight.default_input = weight_init.initializer(weight_init.TruncatedNormal(),
                                                                    cell.weight.default_input.shape,
                                                                    cell.weight.default_input.dtype).to_tensor()
    if not config.use_label_smooth:
        config.label_smooth_factor = 0.0
    loss = CrossEntropy(smooth_factor=config.label_smooth_factor, num_classes=config.class_num)
    loss_scale = FixedLossScaleManager(config.loss_scale, drop_overflow_update=False)

    # define dataset
    dataset = create_dataset(dataset_path=args_opt.dataset_path,
                             do_train=True,
                             repeat_num=epoch_size,
                             batch_size=config.batch_size,
                             target=args_opt.device_target)
    step_size = dataset.get_dataset_size()

    if quant_set.quantization_aware:
        # convert fusion network to quantization aware network
        net = quant.convert_quant_network(net, bn_fold=True, per_channel=[True, False], symmetric=[True, False])

    # get learning rate
    lr = get_lr(lr_init=config.lr_init,
                lr_end=0.0,
                lr_max=config.lr_max,
                warmup_epochs=config.warmup_epochs,
                total_epochs=config.epoch_size,
                steps_per_epoch=step_size,
                lr_decay_mode='cosine')
    if args_opt.pre_trained:
        lr = lr[config.pretrained_epoch_size * step_size:]
    lr = Tensor(lr)

    # define optimization
    opt = Momentum(filter(lambda x: x.requires_grad, net.get_parameters()), lr, config.momentum,
                   config.weight_decay, config.loss_scale)

    # define model
    if quant_set.quantization_aware:
        model = Model(net, loss_fn=loss, optimizer=opt, loss_scale_manager=loss_scale, metrics={'acc'})
    else:
        model = Model(net, loss_fn=loss, optimizer=opt, loss_scale_manager=loss_scale, metrics={'acc'},
                      amp_level="O2")

    print("============== Starting Training ==============")
    time_callback = TimeMonitor(data_size=step_size)
    loss_callback = LossMonitor()
    callbacks = [time_callback, loss_callback]
    if rank_id == 0:
        if config.save_checkpoint:
            config_ckpt = CheckpointConfig(save_checkpoint_steps=config.save_checkpoint_epochs * step_size,
                                           keep_checkpoint_max=config.keep_checkpoint_max)
            ckpt_callback = ModelCheckpoint(prefix="ResNet50",
                                            directory=config.save_checkpoint_path,
                                            config=config_ckpt)
            callbacks += [ckpt_callback]
    model.train(epoch_size, dataset, callbacks=callbacks)
    print("============== End Training ==============")
