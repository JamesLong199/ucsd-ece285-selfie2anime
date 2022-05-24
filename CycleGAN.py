import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
from itertools import chain

from models import Generator, Discriminator
from losses import *

# image buffer class used to store generated images
class ImageBuffer():
    def __init__(self, size=50):
        self.buffer_size = size
        if size > 0:
            self.images = []
            self.num_images = 0
    
    def query(self, images):
        '''
        input
            -- images: list of generated images (tensor)
        
        output
            -- return images: list of images (tensor) chosen randomly from input and buffer
        
        By 50/100, return input images
        By 50/100, return images previously stored in the buffer, and insert current images to the buffer 

        '''

        if self.buffer_size == 0:    # If buffer size is 0, do nothing
            return images

        return_images = []

        for image in images:
            image = torch.unsqueeze(image.data, 0)

            if self.num_images < self.buffer_size:     # If image buffer is not full, fill in with input images
                self.images.append(image)
                self.num_images += 1
                return_images.append(image)
            
            else:                
                p = random.uniform(0, 1)

                # by 50% chance, randomly select an image from buffer to return, 
                # and then replace that image with the current input image
                if p > 0.5:                           
                    random_id = random.randint(0, self.buffer_size-1)
                    tmp = self.images[random_id].clone()
                    self.images[random_id] = image
                    return_images.append(tmp)

                # by 50% chance, return the current image
                else:
                    return_images.append(image)
        
        return_images = torch.cat(return_images, 0)
        return return_images

            


class CycleGAN():

    def __init__(self):

        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")

        print('device for CycleGAN:', self.device)

        self.G_12 = self.init_network("Generator")
        self.G_21 = self.init_network("Generator")
        self.D_1 = self.init_network("Discriminator")
        self.D_2 = self.init_network("Discriminator")

        self.G_opt = self.init_optimizer("Adam", chain(self.G_12.parameters(), self.G_21.parameters()), 2e-4)
        self.D_1_opt = self.init_optimizer("Adam", self.D_1.parameters(), 2e-4)
        self.D_2_opt = self.init_optimizer("Adam", self.D_2.parameters(), 2e-4)

        self.fake_1_buffer = self.init_img_buffer(size=50)
        self.fake_2_buffer = self.init_img_buffer(size=50)

        self.lam = 10
        
        self.image_1 = None
        self.image_2 = None
        self.fake_img_1 = None
        self.fake_img_2 = None
        self.rec_img_1 = None
        self.rec_img_2 = None
        self.id_img_1 = None
        self.id_img_2 = None
        
        self.loss_fn_GAN = GAN_Loss()
        self.loss_fn_cycle = Cycle_Loss()
        self.loss_fn_id = Identity_Loss()
        self.loss_fn_D = Discriminator_Loss()
        
        self.loss_G = None
        self.loss_D1 = None
        self.loss_D2 = None


    def init_network(self, net_type):
        net = None
        if net_type == 'Generator':
            net = Generator()
        elif net_type == 'Discriminator':
            net = Discriminator()
        else:
            raise NotImplementedError("This network is not implemented!")
        
        net.to(self.device)
        
        net.apply(self.init_weights_GAN)
        return net


    def init_optimizer(self, optimizer, model_params, learning_rate):
        opt = None

        if optimizer == "Adam":
            opt = optim.Adam(model_params, learning_rate)
        else: 
            raise NotImplementedError("Optimizer has not been implemented yet!")

        return opt        


    def init_weights_GAN(self, layer):
        '''
        initialize all layer weights to be N(0,0.02) as in the original GAN paper

        '''
        if isinstance(layer, nn.Linear):
            nn.init.normal(layer.weight, 0., 0.02)
        elif isinstance(layer, nn.Conv2d):
            nn.init.normal(layer.weight, 0., 0.02)


    def init_img_buffer(self, size=50):
        return ImageBuffer(size)

    
    def set_mode_train(self):
        '''
        set all network to train mode

        '''
        self.G_12.train()
        self.G_21.train()
        self.D_1.train()
        self.D_2.train()


    def set_mode_eval(self):
        '''
        set all network to eval mode
        
        '''
        self.G_12.eval()
        self.G_21.eval()
        self.D_1.eval()
        self.D_2.eval()

    
    def set_input_images(self, images_1, images_2):
        '''
        save input images for the networks
        
        '''
        
        self.images_1 = images_1
        self.images_2 = images_2
    

    def update_gradient_G(self):
        '''
        forward pass, compute loss and update gradient for generators

        '''

        self.fake_img_2 = self.G_12(self.images_1)
        self.fake_img_1 = self.G_21(self.images_2)

        rec_2 = self.G_12(self.fake_img_1)
        rec_1 = self.G_21(self.fake_img_2)

        id_2 = self.G_12(self.images_2)
        id_1 = self.G_21(self.images_1)
        
        fake_score_1 = self.D_1(self.fake_img_1)
        fake_score_2 = self.D_2(self.fake_img_2)
        
        loss_GAN = self.loss_fn_GAN(fake_score_1) + self.loss_fn_GAN(fake_score_2)
        loss_cycle = self.loss_fn_cycle(rec_1, self.images_1) + self.loss_fn_cycle(rec_2, self.images_2)
        loss_id = self.loss_fn_id(id_1, self.images_1) + self.loss_fn_id(id_2, self.images_2)
        
        self.loss_G = loss_GAN + self.lam * loss_cycle + loss_id
        
        self.G_opt.zero_grad()
        self.loss_G.backward()
        self.G_opt.step()
        
        
        
    def update_gradient_D(self):
        '''
        query generated images from buffer, forward pass, compute loss
        and update gradient for discriminators
        
        '''
        fake_img_1 = self.fake_1_buffer.query(self.fake_img_1)
        fake_img_2 = self.fake_2_buffer.query(self.fake_img_2)
        
        real_score_1 = self.D_1(self.images_1)
        fake_score_1 = self.D_1(fake_img_1)
        real_score_2 = self.D_2(self.images_2)
        fake_score_2 = self.D_2(fake_img_2)
        
        self.loss_D1 = self.loss_fn_D(real_score_1, fake_score_1)
        self.loss_D2 = self.loss_fn_D(real_score_2, fake_score_2)
        
        
        self.D_1_opt.zero_grad()
        self.loss_D1.backward()
        self.D_1_opt.step()
        
        self.D_2_opt.zero_grad()
        self.loss_D2.backward()
        self.D_2_opt.step()
        