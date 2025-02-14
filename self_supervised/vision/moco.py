# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/11 - moco.ipynb (unless otherwise specified).

__all__ = ['MoCoModel', 'create_moco_model', 'get_moco_aug_pipelines', 'MOCO']

# Cell
from fastai.vision.all import *
from ..augmentations import *
from ..layers import *

# Cell
class MoCoModel(Module):
    # TODO: Add queue as buffer to torch module, is it needed for distrib??
    "MoCo model"
    def __init__(self,encoder,projector):
        self.encoder,self.projector = encoder,projector

    def forward(self,x):
        return F.normalize(self.projector(self.encoder(x)), dim=1)

# Cell
def create_moco_model(encoder, hidden_size=256, projection_size=128, bn=False, nlayers=2):
    "Create MoCo model"
    n_in  = in_channels(encoder)
    with torch.no_grad(): representation = encoder(torch.randn((2,n_in,128,128)))
    projector = create_mlp_module(representation.size(1), hidden_size, projection_size, bn=bn, nlayers=nlayers)
    apply_init(projector)
    return MoCoModel(encoder, projector)

# Cell
@delegates(get_multi_aug_pipelines)
def get_moco_aug_pipelines(size, **kwargs): return get_multi_aug_pipelines(n=2, size=size, **kwargs)

# Cell
from copy import deepcopy

class MOCO(Callback):
    order,run_valid = 9,True
    def __init__(self,  aug_pipelines, K,  m=0.999, temp=0.07, print_augs=False):
        assert_aug_pipelines(aug_pipelines)
        self.aug1, self.aug2 = aug_pipelines
        if print_augs: print(self.aug1), print(self.aug2)
        store_attr('K,m,temp')


    def before_fit(self):
        "Create key encoder and init queue"
        if (not hasattr(self, "encoder_k")) and (not hasattr(self, "queue")):
            # init key encoder
            self.encoder_k = deepcopy(self.learn.model).to(self.dls.device)
            for param_k in self.encoder_k.parameters(): param_k.requires_grad = False
            # init queue
            nf = self.learn.model.projector[-1].out_features
            self.queue = torch.randn(self.K, nf).to(self.dls.device)
            self.queue = nn.functional.normalize(self.queue, dim=1)
            self.queue_ptr = 0
        else: raise Exception("Key encoder and queue is already defined")

        self.learn.loss_func = self.lf


    def before_batch(self):
        "Generate query and key for the current batch"
        q_img,k_img = self.aug1(self.x), self.aug2(self.x.clone())
        self.learn.xb = (q_img,)
        with torch.no_grad(): self.learn.yb = (self.encoder_k(k_img),)


    def lf(self, pred, *yb):
        q,k = pred,yb[0]
        logits = q @ torch.cat([k, self.queue]).T / self.temp # Nx(N+K) instead of original Nx(1+K)
        labels = torch.arange(len(q)).to(self.dls.device)
        return F.cross_entropy(logits, labels)


    @torch.no_grad()
    def _momentum_update_key_encoder(self):
        for param_q, param_k in zip(self.learn.model.parameters(), self.encoder_k.parameters()):
            param_k.data = param_k.data * self.m + param_q.data * (1. - self.m)


    @torch.no_grad()
    def _dequeue_and_enqueue(self):
        bs = self.x.size(0)
        k = self.y
        assert self.K % bs == 0  # for simplicity
        self.queue[self.queue_ptr:self.queue_ptr+bs, :] = k
        self.queue_ptr = (self.queue_ptr + bs) % self.K  # move pointer


    def after_step(self):
        "Update momentum (key) encoder and queue"
        self._momentum_update_key_encoder()
        self._dequeue_and_enqueue()


    @torch.no_grad()
    def show(self, n=1):
        x1,x2  = self.aug1(self.x), self.aug2(self.x.clone())
        bs = x1.size(0)
        idxs = np.random.choice(range(bs),n,False)
        x1 = self.aug1.decode(x1[idxs].to('cpu').clone()).clamp(0,1)
        x2 = self.aug2.decode(x2[idxs].to('cpu').clone()).clamp(0,1)
        images = []
        for i in range(n): images += [x1[i],x2[i]]
        return show_batch(x1[0], None, images, max_n=len(images), ncols=None, nrows=n)