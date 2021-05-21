_base_ = [
    './cascade_rcnn_r50_fpn.py',
    '../dataset_basic.py',
    '../../_base_/schedules/schedule_1x.py',
    '../../_base_/default_runtime.py'
]

model = dict(
    backbone=dict(
        type='DetectoRS_ResNet',
        conv_cfg=dict(type='ConvAWS'),
        sac=dict(type='SAC', use_deform=True),
        stage_with_sac=(False, True, True, True),
        output_img=True),
    neck=dict(
        type='RFP',
        rfp_steps=2,
        aspp_out_channels=64,
        aspp_dilations=(1, 3, 6, 1),
        rfp_backbone=dict(
            rfp_inplanes=256,
            type='DetectoRS_ResNet',
            depth=50,
            num_stages=4,
            out_indices=(0, 1, 2, 3),
            frozen_stages=1,
            norm_cfg=dict(type='BN', requires_grad=True),
            norm_eval=True,
            conv_cfg=dict(type='ConvAWS'),
            sac=dict(type='SAC', use_deform=True),
            stage_with_sac=(False, True, True, True),
            pretrained='torchvision://resnet50',
            style='pytorch',
            plugins=[
                    dict(
                        cfg=dict(
                            type='GeneralizedAttention',
                            spatial_range=-1,
                            num_heads=8,
                            attention_type='0010',
                            kv_stride=2),
                        stages=(False, False, True, True),
                        position='after_conv2')
                    ]
        )))

checkpoint_config = dict(max_keep_ckpts=12, interval=1)

#data = dict(samples_per_gpu=2)
optimizer = dict(lr=0.01)

lr_config = dict(step=[43, 47])
runner = dict(type='EpochBasedRunner', max_epochs=48)




