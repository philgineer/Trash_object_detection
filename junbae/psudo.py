
import torch
from dataset import COCODataLoader
from torch.utils.data import Subset, DataLoader, Dataset
import torchvision.transforms as transforms

from utils import seed_everything
from models.DeepV3 import *
import random
import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
import torch.nn.functional as F
from utils import label_accuracy_score, seed_everything, add_hist
from models.smp import *

def collate_fn(batch):
    return tuple(zip(*batch))


def validation(epoch, model, data_loader, criterion, device, n_class):
    print('Start validation #{}'.format(epoch))
    model.eval()
    with torch.no_grad():
        total_loss = 0
        cnt = 0
        mIoU_list = []
        hist = np.zeros((n_class, n_class))  # 중첩을위한 변수
        for step, (images, masks, _) in enumerate(data_loader):

            # (batch, channel, height, width)
            images = torch.stack(images)
            # (batch, channel, height, width)
            masks = torch.stack(masks).long()

            images, masks = images.to(device), masks.to(device)

            outputs = model(images)
            loss = criterion(outputs, masks)
            total_loss += loss
            cnt += 1

            outputs = torch.argmax(
                outputs.squeeze(), dim=1).detach().cpu().numpy()

            # 계산을 위한 중첩
            hist = add_hist(hist, masks.detach().cpu().numpy(),
                            outputs, n_class=n_class)

            # mIoU = label_accuracy_score(
            #     masks.detach().cpu().numpy(), outputs, n_class=12)[2]
            # mIoU_list.append(mIoU)

        # mIoU가 전체에대해 계산
        acc, acc_cls, mIoU, fwavacc = label_accuracy_score(hist)
        avrg_loss = total_loss / cnt
        print('Validation #{}  Average Loss: {:.4f}, mIoU: {:.4f}'.format(
            epoch, avrg_loss, mIoU))
    return avrg_loss, mIoU


def alpha_weight(epoch):
    T1 = 100
    T2 = 700
    af = 3
    if epoch < T1:
        return 0.0
    elif epoch > T2:
        return af
    else:
        return ((epoch-T1) / (T2-T1))*af


def psudo_labeling(num_epochs, model, data_loader, val_loader, unlabeled_loader, criterion, optimizer, device, n_class):
    # Instead of using current epoch we use a "step" variable to calculate alpha_weight
    # This helps the model converge faster
    step = 100
    size = 256
    transform = A.Compose([A.Resize(256, 256)])
    preds_array = np.empty((0, size*size), dtype=np.long)
    file_name_list = []
    model.train()
    for epoch in range(num_epochs):
        hist = np.zeros((n_class, n_class))
        for batch_idx, (imgs, image_infos) in enumerate(unlabeled_loader):

            # Forward Pass to get the pseudo labels
            #--------------------------------------------- test(unlabelse)를 모델에 통과
            model.eval()
            outs = model(torch.stack(imgs).to(device))
            oms = torch.argmax(
                outs.squeeze(), dim=1).detach().cpu().numpy()
            oms = torch.Tensor(oms)
            oms = oms.long()
            oms = oms.to(device)

            #--------------------------------------------- 학습

            model.train()
            # Now calculate the unlabeled loss using the pseudo label
            imgs = torch.stack(imgs)
            imgs = imgs.to(device)
            # preds_array = preds_array.to(device)

            output = model(imgs)

           
            unlabeled_loss = alpha_weight(
                step) * criterion(output, oms)

            # Backpropogate
            optimizer.zero_grad()
            unlabeled_loss.backward()
            optimizer.step()
            output = torch.argmax(
                output.squeeze(), dim=1).detach().cpu().numpy()
            hist = add_hist(hist, oms.detach().cpu().numpy(),
                            output, n_class=n_class)
            
            # For every 50 batches train one epoch on labeled data
            # 50배치마다 라벨데이터를 1 epoch학습
            if (batch_idx + 1) % 25 == 0:
                acc, acc_cls, mIoU, fwavacc = label_accuracy_score(hist)
                print('Epoch [{}/{}], Step [{}/{}], Loss: {:.4f}, mIoU:{:.4f}'.format(
                    epoch+1, num_epochs, batch_idx+1, len(unlabeled_loader), unlabeled_loss.item(), mIoU))
            if batch_idx % 50 == 0:

                # Normal training procedure
                for batch_idx, (images, masks, _) in enumerate(train_loader):
                    images = torch.stack(images)
                    # (batch, channel, height, width)
                    masks = torch.stack(masks).long()

                    # gpu 연산을 위해 device 할당
                    images, masks = images.to(device), masks.to(device)

                    output = model(images)
                    labeled_loss = criterion(output, masks)

                    optimizer.zero_grad()
                    labeled_loss.backward()
                    optimizer.step()

                # Now we increment step by 1
                step += 1

        avrg_loss, val_mIoU = validation(
            epoch + 1, model, val_loader, criterion, device, n_class)

        print('Epoch: {} : Alpha Weight : {:.5f} | Test miou/ : {:.5f} | Test loss : {:.3f} '.format(
            epoch, alpha_weight(step), val_mIoU, avrg_loss))

        model.train()


def save_model(model, saved_dir, file_name):
    check_point = {'net': model.state_dict()}
    output_path = os.path.join(saved_dir, file_name)
    torch.save(model.state_dict(), output_path)


if __name__ == '__main__':
    seed_everything(21)
    dataset_path = '../../input/data'
    train_path = dataset_path + '/train.json'
    val_path = dataset_path + '/val.json'
    test_path = dataset_path + '/test.json'

    device = "cuda" if torch.cuda.is_available() else "cpu"
    acc_scores = []
    unlabel = []
    pseudo_label = []

    alpha_log = []
    test_acc_log = []
    test_loss_log = []
    batch_size = 8   # Mini-batch size
    num_epochs = 20
    learning_rate = 0.0001
    weight_decay = 1e-6
    val_every = 1

    category_names = ['Backgroud',
                      'UNKNOWN',
                      'General trash',
                      'Paper',
                      'Paper pack',
                      'Metal',
                      'Glass',
                      'Plastic',
                      'Styrofoam',
                      'Plastic bag',
                      'Battery',
                      'Clothing']
    # 데이터셋
    test_transform = A.Compose([
        ToTensorV2()
    ])
    test_dataset = COCODataLoader(
        data_dir=test_path, dataset_path=dataset_path,  mode='test',  category_names=category_names, transform=test_transform)
    test_loader = torch.utils.data.DataLoader(dataset=test_dataset,
                                              batch_size=batch_size,
                                              num_workers=4,
                                              collate_fn=collate_fn)
    train_transform = A.Compose([
        ToTensorV2()
    ])

    train_dataset = COCODataLoader(
        data_dir=train_path, dataset_path=dataset_path, mode='train', category_names=category_names, transform=train_transform)
    train_loader = torch.utils.data.DataLoader(dataset=train_dataset,
                                               batch_size=batch_size,
                                               shuffle=True,
                                               num_workers=4,
                                               collate_fn=collate_fn,
                                               drop_last=True)
    val_transform = A.Compose([
        ToTensorV2()
    ])
    val_dataset = COCODataLoader(
        data_dir=val_path, dataset_path=dataset_path,  mode='val', category_names=category_names, transform=val_transform)

    val_loader = torch.utils.data.DataLoader(dataset=val_dataset,
                                             batch_size=batch_size,
                                             shuffle=False,
                                             num_workers=4,
                                             collate_fn=collate_fn,
                                             drop_last=True)

    category_names = ['Backgroud',
                      'UNKNOWN',
                      'General trash',
                      'Paper',
                      'Paper pack',
                      'Metal',
                      'Glass',
                      'Plastic',
                      'Styrofoam',
                      'Plastic bag',
                      'Battery',
                      'Clothing']
    # 모델
    model_path = './saved/fpn_b16_e20.pt'

    model = get_smp_model('FPN','efficientnet-b0')

    checkpoint = torch.load(model_path, map_location=device)
    model = model.to(device)
    model.load_state_dict(checkpoint)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(
        params=model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    psudo_labeling(num_epochs, model, train_loader, val_loader, test_loader, criterion,
                   optimizer, device, n_class=12)

    save_model(model, './saved', 'psudo_test.pt')
