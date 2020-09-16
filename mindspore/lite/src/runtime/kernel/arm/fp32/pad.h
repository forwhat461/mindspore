/**
 * Copyright 2020 Huawei Technologies Co., Ltd
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#ifndef MINDSPORE_LITE_SRC_RUNTIME_KERNEL_ARM_FP32_PAD_H_
#define MINDSPORE_LITE_SRC_RUNTIME_KERNEL_ARM_FP32_PAD_H_

#include <vector>
#include "src/lite_kernel.h"

#include "nnacl/fp32/pad.h"
#include "src/runtime/kernel/arm/base/layout_transform.h"

namespace mindspore::kernel {
class PadCPUKernel : public LiteKernel {
 public:
  PadCPUKernel(OpParameter *parameter, const std::vector<lite::Tensor *> &inputs,
               const std::vector<lite::Tensor *> &outputs, const lite::Context *ctx,
               const mindspore::lite::PrimitiveC *primitive)
      : LiteKernel(parameter, inputs, outputs, ctx, primitive) {
    pad_param_ = reinterpret_cast<PadParameter *>(parameter);
  }

  ~PadCPUKernel() {}

  int Init() override;
  int ReSize() override;
  int Run() override;
  virtual int RunImpl(int task_id);
  int RunMirrorPadImpl(int task_id);

 private:
  int HandleMirrorPad();
  int CheckPaddings(int *paddings, int length, int *input_shape, int mode);
  int CopyPaddingFromInput();
  void CalculateStrides();
  int ExtendShape(int *shape, int length, const int *ori_shape, int rank);
  int ExtendPaddings(int *paddings, int length, const int *ori_paddings, int ori_length);

 protected:
  PadParameter *pad_param_;
  int in_[4];
  int out_[4];
};

int PadImpl(void *cdata, int task_id);
int MirrorPadImpl(void *cdata, int task_id);
}  // namespace mindspore::kernel

#endif  // MINDSPORE_LITE_SRC_RUNTIME_KERNEL_ARM_FP32_PAD_H_
