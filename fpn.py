'''RetinaFPN in PyTorch.'''
import torch
import torch.nn as nn
import torch.nn.functional as F

from torch.autograd import Variable


class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, in_planes, planes, stride=1):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(in_planes, planes, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(planes, self.expansion*planes, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(self.expansion*planes)

        self.downsample = nn.Sequential()
        if stride != 1 or in_planes != self.expansion*planes:
            self.downsample = nn.Sequential(
                nn.Conv2d(in_planes, self.expansion*planes, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(self.expansion*planes)
            )

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = F.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        out += self.downsample(x)
        out = F.relu(out)
        return out


class FPN(nn.Module):
    num_layers: torch.jit.Final[int]
    num_fpn_layers: torch.jit.Final[int]
    fpn_skip_layers: torch.jit.Final[int]
    def __init__(self, block, num_blocks, num_layers=5, num_fpn_layers=0, fpn_skip_layers=0):
        super(FPN, self).__init__()
        self.in_planes = 64

        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3, bias=False)
        self.bn1 = nn.BatchNorm2d(64)

        # Bottom-up layers
        self.layer1 = self._make_layer(block,  64, num_blocks[0], stride=1)
        self.layer2 = self._make_layer(block, 128, num_blocks[1], stride=2)
        self.layer3 = self._make_layer(block, 256, num_blocks[2], stride=2)
        self.layer4 = self._make_layer(block, 512, num_blocks[3], stride=2)
        self.conv6 = nn.Conv2d(2048, 256, kernel_size=3, stride=2, padding=1)
        self.conv7 = nn.Conv2d( 256, 256, kernel_size=3, stride=2, padding=1)

        # Lateral layers
        self.latlayer1 = nn.Conv2d(2048, 256, kernel_size=1, stride=1, padding=0)
        self.latlayer2 = nn.Conv2d(1024, 256, kernel_size=1, stride=1, padding=0)
        self.latlayer3 = nn.Conv2d( 512, 256, kernel_size=1, stride=1, padding=0)

        # Top-down layers
        self.toplayer1 = nn.Conv2d(256, 256, kernel_size=3, stride=1, padding=1)
        self.toplayer2 = nn.Conv2d(256, 256, kernel_size=3, stride=1, padding=1)

        self.num_layers = num_layers
        self.num_fpn_layers = max(num_fpn_layers, num_layers)
        self.fpn_skip_layers = fpn_skip_layers

    def _make_layer(self, block, planes, num_blocks, stride):
        strides = [stride] + [1]*(num_blocks-1)
        layers = []
        for stride in strides:
            layers.append(block(self.in_planes, planes, stride))
            self.in_planes = planes * block.expansion
        return nn.Sequential(*layers)

    def _upsample_add(self, x, y):
        '''Upsample and add two feature maps.

        Args:
          x: (Variable) top feature map to be upsampled.
          y: (Variable) lateral feature map.

        Returns:
          (Variable) added feature map.

        Note in PyTorch, when input size is odd, the upsampled feature map
        with `F.upsample(..., scale_factor=2, mode='nearest')`
        maybe not equal to the lateral feature map size.

        e.g.
        original input size: [N,_,15,15] ->
        conv2d feature map size: [N,_,8,8] ->
        upsampled feature map size: [N,_,16,16]

        So we choose bilinear upsample which supports arbitrary output sizes.
        '''
        _,_,H,W = y.size()
        if x is not None and len(x.shape) != 0:
            return F.upsample(x, size=(H,W), mode='bilinear', align_corners=False) + y
        else:
            return y

    def forward(self, x):
        # Bottom-up
        c1 = F.relu(self.bn1(self.conv1(x)))
        c1 = F.max_pool2d(c1, kernel_size=3, stride=2, padding=1)
        c2 = self.layer1(c1)
        c3 = self.layer2(c2)
        p4=torch.tensor(0)
        p5=torch.tensor(0)
        p6=torch.tensor(0)
        p7=torch.tensor(0)
        if self.num_fpn_layers >= 2:
            c4 = self.layer3(c3)
            if self.num_fpn_layers >= 3:
                c5 = self.layer4(c4)
                if self.num_fpn_layers >= 4:
                    p6 = self.conv6(c5)
                    if self.num_fpn_layers >= 5:
                        p7 = self.conv7(F.relu(p6))
                # Top-down
                p5 = self.latlayer1(c5)
            p4 = self._upsample_add(p5, self.latlayer2(c4))
            p4 = self.toplayer1(p4)
        p3 = self._upsample_add(p4, self.latlayer3(c3))
        p3 = self.toplayer2(p3)
        return (p3, p4, p5, p6, p7)[self.fpn_skip_layers:(self.fpn_skip_layers + self.num_layers)]


def FPN50(num_layers=5, num_fpn_layers=0, fpn_skip_layers=0):
    return FPN(Bottleneck, [3,4,6,3], num_layers=num_layers, num_fpn_layers=num_fpn_layers, fpn_skip_layers=fpn_skip_layers)

def FPN101(num_layers=5, num_fpn_layers=0, fpn_skip_layers=0):
    return FPN(Bottleneck, [2,4,23,3], num_layers=num_layers, num_fpn_layers=num_fpn_layers, fpn_skip_layers=fpn_skip_layers)


def test():
    net = FPN50()
    fms = net(Variable(torch.randn(1,3,600,300)))
    for fm in fms:
        print(fm.size())

# test()
