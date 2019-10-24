import argparse
import torchvision.transforms as transforms
from torch.utils.data import DataLoader
from torch.autograd import Variable
import torch
import itertools

from model import Generator
from model import Discriminator
from utils import ReplayBuffer
from utils import LambdaLR
from utils import Logger
from utils import weights_init_normal
from dataset import ImgDataset



def main(args):
    # writer = SummaryWriter(os.path.join(args.out_dir, 'logs'))
    G_AB = Generator(args.in_channel, args.out_channel).to(args.device)
    G_BA = Generator(args.in_channel, args.out_channel).to(args.device)
    D_A = Discriminator(args.in_channel).to(args.device)
    D_B = Discriminator(args.out_channel).to(args.device)

    G_AB.apply(weights_init_normal)
    G_BA.apply(weights_init_normal)
    D_A.apply(weights_init_normal)
    D_B.apply(weights_init_normal)

    criterion_GAN = torch.nn.MSELoss()
    criterion_cycle = torch.nn.L1Loss()
    criterion_identity = torch.nn.L1Loss()

    optimizer_G = torch.optim.Adam(itertools.chain(G_AB.parameters(), G_BA.parameters()),
                                   lr=args.lr, betas=(0.5, 0.999))
    optimizer_D_A = torch.optim.Adam(D_A.parameters(), lr=args.lr, betas=(0.5, 0.999))
    optimizer_D_B = torch.optim.Adam(D_B.parameters(), lr=args.lr, betas=(0.5, 0.999))

    lr_scheduler_G = torch.optim.lr_scheduler.LambdaLR(optimizer_G, lr_lambda=LambdaLR(args.n_epochs, args.epoch, args.decay_epoch).step)
    lr_scheduler_D_A = torch.optim.lr_scheduler.LambdaLR(optimizer_D_A, lr_lambda=LambdaLR(args.n_epochs, args.epoch, args.decay_epoch).step)
    lr_scheduler_D_B = torch.optim.lr_scheduler.LambdaLR(optimizer_D_B, lr_lambda=LambdaLR(args.n_epochs, args.epoch, args.decay_epoch).step)

    fake_A_buffer = ReplayBuffer()
    fake_B_buffer = ReplayBuffer()

    transforms_ = [
                    transforms.ToTensor(),
                    transforms.Normalize((0.5,0.5,0.5), (0.5,0.5,0.5)) ]
    dataloader = DataLoader(ImgDataset(args.dataset_path, transforms_=transforms_, unaligned=True, device=args.device),
                            batch_size=args.batchSize, shuffle=True, num_workers=0)
    logger = Logger(args.n_epochs, len(dataloader))
    target_real = Variable(torch.Tensor(args.batchSize,1).fill_(1.)).to(args.device).detach()
    target_fake = Variable(torch.Tensor(args.batchSize,1).fill_(0.)).to(args.device).detach()

    for epoch in range(args.epoch, args.n_epochs):
        for i, batch in enumerate(dataloader):
            real_A = batch['A'].clone()
            real_B = batch['B'].clone()

            optimizer_G.zero_grad()

            #gan loss
            fake_b = G_AB(real_A)
            pred_fakeb = D_B(fake_b)
            loss_gan_AB = criterion_GAN(pred_fakeb, target_real)

            fake_a = G_BA(real_B)
            pred_fakea = D_A(fake_a)
            loss_gan_BA = criterion_GAN(pred_fakea, target_real)

            #identity loss
            same_b = G_AB(real_B)
            loss_identity_B = criterion_identity(same_b, real_B)*5
            same_a = G_BA(real_A)
            loss_identity_A = criterion_identity(same_a, real_A)*5

            #cycle consistency loss
            recovered_A = G_BA(fake_b)
            recovered_B = G_AB(fake_a)
            loss_cycle_ABA = criterion_cycle(recovered_A, real_A)*10
            loss_cycle_BAB = criterion_cycle(recovered_B, real_B)*10

            loss_G = loss_gan_AB + loss_gan_BA + loss_identity_B + loss_identity_A + loss_cycle_ABA + loss_cycle_BAB
            loss_G.backward()

            optimizer_G.step()

            ##discriminator a
            optimizer_D_A.zero_grad()

            pred_realA = D_A(real_A)
            loss_D_A_real = criterion_GAN(pred_realA, target_real)

            fake_A = fake_A_buffer.push_and_pop(fake_a)
            pred_fakeA = D_A(fake_A.detach())
            loss_D_A_fake = criterion_GAN(pred_fakeA, target_fake)

            loss_D_A = (loss_D_A_real + loss_D_A_fake)*0.5
            loss_D_A.backward()

            optimizer_D_A.step()

            #discriminator b
            optimizer_D_B.zero_grad()

            pred_realB = D_B(real_B)
            loss_D_B_real = criterion_GAN(pred_realB, target_real)

            fake_B = fake_B_buffer.push_and_pop(fake_b)
            pred_fakeB = D_B(fake_B.detach())
            loss_D_B_fake = criterion_GAN(pred_fakeB, target_fake)

            loss_D_B = (loss_D_B_real + loss_D_B_fake)*0.5
            loss_D_B.backward()

            optimizer_D_B.step()

            logger.log({'loss_G': loss_G, 'loss_G_identity': (loss_identity_A + loss_identity_B), 'loss_G_GAN': (loss_gan_AB + loss_gan_BA),
                        'loss_G_cycle': (loss_cycle_ABA + loss_cycle_BAB), 'loss_D': (loss_D_A + loss_D_B)},
                       images={'real_A': real_A, 'real_B': real_B, 'fake_A': fake_a, 'fake_B': fake_b},
                       out_dir=os.path.join(args.out_dir, 'logs', str(epoch)))
        lr_scheduler_G.step()
        lr_scheduler_D_A.step()
        lr_scheduler_D_B.step()


if __name__ == '__main__':
    import os

    parser = argparse.ArgumentParser()

    parser.add_argument('--dataset_path', type=str, help='path to the dataset')
    parser.add_argument('--model_path', type=str, help='path to the model checkpoint', default=None)
    parser.add_argument('--out_dir', type=str, help='output dir', default='./')
    parser.add_argument('--device', type=str, help='set the device', default='cuda')
    parser.add_argument('--model_name', type=str, help='name of model', default='cygan')

    parser.add_argument('--epoch', type=int, default=0, help='starting epoch')
    parser.add_argument('--n_epochs', type=int, default=200, help='number of epochs of training')
    parser.add_argument('--batchSize', type=int, default=1, help='size of the batches')
    parser.add_argument('--lr', type=float, default=0.0002, help='initial learning rate')
    parser.add_argument('--decay_epoch', type=int, default=100, help='epoch to start decaying lr')
    # parser.add_argument('--size', type=int, default=256, help='size of the data crop (squared assumed)')
    parser.add_argument('--in_channel', type=int, default=3, help='number of channels of input data')
    parser.add_argument('--out_channel', type=int, default=3, help='number of channels of output data')
    parser.add_argument('--n_cpu', type=int, default=1, help='number of cpu threads to use during batch generation')
    args = parser.parse_args()
    print(args)

    if torch.cuda.is_available() and args.device != 'cuda':
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

    if not os.path.exists(os.path.join(args.out_dir, 'logs')):
        os.makedirs(os.path.join(args.out_dir, 'logs'))
    if not os.path.exists(os.path.join(args.out_dir, 'models')):
        os.makedirs(os.path.join(args.out_dir, 'models'))

    args.device = torch.device(args.device)
    main(args)
