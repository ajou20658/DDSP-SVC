import PySimpleGUI as sg
import sounddevice as sd
import torch,librosa,threading,time,queue
from enhancer import Enhancer
import numpy as np
from ddsp.vocoder import load_model, F0_Extractor, Volume_Extractor, Units_Encoder
from ddsp.core import upsample
import matplotlib.pyplot as plt
def launcher():
    '''窗口加载'''
    sg.theme('DarkAmber')   # 设置主题
    # 界面布局
    layout = [
        [sg.Frame(layout=[
            [sg_model,sg.FileBrowse('选择模型文件')]
            ],title='模型.pt格式(自动识别同目录下config.yaml)')],
        [sg.Frame(layout=[
            [sg.Text("输入设备"),sg_input_device],
            [sg.Text("输出设备"),sg_output_device]
            ],title='音频设备')],
        [sg.Frame(layout=[
            [sg.Text("降噪设置"),sg_noise],
            [sg.Text("音频切分大小"),sg_block],
            [sg.Text("变调"),sg_pitch],
            [sg.Text("f0预测模式"),sg_f0mode],
            [sg.Text("采样率"),sg_samplerate]
            ],title='设置'),
        sg.Frame(layout=[
            [sg.Text("交叉淡化时长"),sg_crossfade],
            [sg.Text("使用历史区块数量"),sg_buffer_num]
            ],title='设置')
         ],
        [sg.Button("开始音频转换",key="start_vc"),sg.Button("停止音频转换",key="stop_vc")]
    ]

    # 创造窗口
    window = sg.Window('DDSP - GUI by INT16', layout)
    event_handler(window=window)


def audio_callback(indata,outdata, frames, time, status):
    '''音频处理'''
    global input_wav,output_wav,temp_wav,crossfade_last
    #print('indata shape:'+str(indata.shape))
    print("Realtime VCing...")
    input_wav[:]=np.roll(input_wav,-block_frame)
    input_wav[-block_frame:]=librosa.to_mono(indata.T)
    print('input_wav.shape:'+str(input_wav.shape))
    _audio, _model_sr = svc_model.infer( f_pitch_change, spk_id, f_safe_prefix_pad_length,input_wav,samplerate)
    temp_wav[:] = librosa.resample(_audio, orig_sr=_model_sr, target_sr=samplerate)[-block_frame-crossfade_frame:]
    #cross fade output_wav's start with last crossfade
    output_wav[:]=temp_wav[:block_frame]
    output_wav[:crossfade_frame]*=fade_in_window
    output_wav[:crossfade_frame]+=crossfade_last
    crossfade_last[:]=temp_wav[-crossfade_frame:]
    crossfade_last[:]*=fade_out_window
    #output_wav[:]=librosa.resample(_audio, orig_sr=_model_sr, target_sr=samplerate)[-block_frame:]
    print("infered _audio.shape:"+str(_audio.shape)+',samplerate:'+str(_model_sr))
    outdata[:] = np.array([output_wav, output_wav]).T
    print('Outputed.')
    
    '''
    output_wave:np.ndarray = librosa.resample(_audio, orig_sr=_model_sr, target_sr=samplerate)[:outdata.shape[0]]
    output_wave[:fade_samples]*=fade_in_window
    output_wave[-fade_samples:]*=fade_out_window
    '''
    
    
    '''time2 = np.arange(0, len(input_wav)) * (1.0 / samplerate)
    plt.cla()
    plt.plot(time2, input_wav)
    plt.title("input_wave")
    plt.xlabel("time")
    plt.ylabel("amp")
    plt.savefig(".\\input.png", dpi=600)
    time2 = np.arange(0, len(_audio)) * (1.0 / samplerate)
    plt.cla()
    plt.plot(time2, _audio)
    plt.title("_audio")
    plt.xlabel("time")
    plt.ylabel("amp")
    plt.savefig(".\\output.png", dpi=600)'''
    
    

def soundinput():
    '''
    接受音频输入
    '''
    global flag_vc
    with sd.Stream(callback=audio_callback, blocksize=block_frame,samplerate=samplerate,dtype='float32'):
        while flag_vc:
            time.sleep(block_time)
            print('Audio block passed.')
    print('ENDing VC')


def start_vc():
    '''开始音频转换'''
    global flag_vc,svc_model,fade_in_window,fade_out_window,input_wav,output_wav,temp_wav,crossfade_last
    flag_vc = True
    #初始化一下各个ndarray
    input_wav=np.zeros(int((1+buffer_num)*block_frame),dtype='float32')
    output_wav=np.zeros(block_frame,dtype='float32')
    temp_wav=np.zeros(block_frame+crossfade_frame,dtype='float32')
    crossfade_last=np.zeros(crossfade_frame,dtype='float32')
    fade_in_window = np.linspace(0, 1,crossfade_frame)
    fade_out_window = np.linspace(1, 0,crossfade_frame)
    svc_model = SvcDDSP(checkpoint_path, use_vocoder_based_enhancer, enhancer_adaptive_key, select_pitch_extractor,limit_f0_min, limit_f0_max, threhold, spk_id, spk_mix_dict, enable_spk_id_cover)
    thread_vc=threading.Thread(target=soundinput)
    thread_vc.start()
    

def event_handler(window):
    '''事件处理'''
    global flag_vc,block_time,f_pitch_change,f_safe_prefix_pad_length,threhold,checkpoint_path,samplerate,buffer_num,crossfade_time,block_frame,crossfade_frame
    while True:#事件处理循环
        event, values = window.read()
        if event ==sg.WINDOW_CLOSED:   # 如果用户关闭窗口或点击`Cancel`
            flag_vc=False
            exit()
        if event=='start_vc' and flag_vc==False:
            set_devices(sg_input_device.get(),sg_output_device.get())
            #set values
            checkpoint_path = sg_model.get()
            f_pitch_change = values['pitch']
            buffer_num= int(values['buffernum'])
            threhold=values['noise']
            crossfade_time=values['crossfade']
            block_time=float(values['block'])
            samplerate=int(values['samplerate'])
            block_frame=int(block_time*samplerate)
            crossfade_frame=int(crossfade_time*samplerate)
            f_safe_prefix_pad_length=block_time*(buffer_num)-crossfade_time*2
            print('crossfade_time:'+str(crossfade_time))
            print("buffer_num:"+str(buffer_num))
            print("samplerate:"+str(samplerate))
            print('block_time:'+str(block_time))
            print("prefix_pad_length:"+str(f_safe_prefix_pad_length))
            start_vc()
        if event=='stop_vc'and flag_vc==True:
            flag_vc = False


def set_devices(input_device,output_device):
    '''设置输出设备'''
    global samplerate
    #print(input_device_indices)
    #print(output_device_indices)
    sd.default.device[0]=input_device_indices[input_devices.index(input_device)]
    sd.default.device[1]=output_device_indices[output_devices.index(output_device)]
    print("input device:"+str(sd.default.device[0])+":"+str(input_device))
    print("output device:"+str(sd.default.device[1])+":"+str(output_device))
    
    

def get_devices(update: bool = True):
    '''获取设备列表'''
    if update:
        sd._terminate()
        sd._initialize()
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    for hostapi in hostapis:
        for device_idx in hostapi["devices"]:
            devices[device_idx]["hostapi_name"] = hostapi["name"]
    input_devices = [
        f"{d['name']} ({d['hostapi_name']})"
        for d in devices
        if d["max_input_channels"] > 0
    ]
    output_devices = [
        f"{d['name']} ({d['hostapi_name']})"
        for d in devices
        if d["max_output_channels"] > 0
    ]
    input_devices_indices = [d["index"] for d in devices if d["max_input_channels"] > 0]
    output_devices_indices = [
        d["index"] for d in devices if d["max_output_channels"] > 0
    ]
    return input_devices, output_devices, input_devices_indices, output_devices_indices


class SvcDDSP:
    def __init__(self, model_path, vocoder_based_enhancer, enhancer_adaptive_key, input_pitch_extractor,
                 f0_min, f0_max, threhold, spk_id, spk_mix_dict, enable_spk_id_cover):
        self.model_path = model_path
        self.vocoder_based_enhancer = vocoder_based_enhancer
        self.enhancer_adaptive_key = enhancer_adaptive_key
        self.input_pitch_extractor = input_pitch_extractor
        self.f0_min = f0_min
        self.f0_max = f0_max
        self.threhold = threhold
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.spk_id = spk_id
        self.spk_mix_dict = spk_mix_dict
        self.enable_spk_id_cover = enable_spk_id_cover
        
        # load ddsp model
        self.model, self.args = load_model(self.model_path, device=self.device)
        
        # load units encoder
        self.units_encoder = Units_Encoder(
            self.args.data.encoder,
            self.args.data.encoder_ckpt,
            self.args.data.encoder_sample_rate,
            self.args.data.encoder_hop_size,
            device=self.device)
        
        # load enhancer
        if self.vocoder_based_enhancer:
            self.enhancer = Enhancer(self.args.enhancer.type, self.args.enhancer.ckpt, device=self.device)

    def infer(self,  pitch_adjust, speaker_id, safe_prefix_pad_length,audio,sample_rate):
        print("Infering...")
        # load input
        #audio, sample_rate = librosa.load(input_wav, sr=None, mono=True)
        hop_size = self.args.data.block_size * sample_rate / self.args.data.sampling_rate
        # safe front silence
        if safe_prefix_pad_length > 0.03:
            silence_front = safe_prefix_pad_length - 0.03
        else:
            silence_front = 0
            
        # extract f0
        pitch_extractor = F0_Extractor(
            self.input_pitch_extractor,
            sample_rate,
            hop_size,
            float(self.f0_min),
            float(self.f0_max))
        f0 = pitch_extractor.extract(audio, uv_interp=True, device=self.device, silence_front=silence_front)
        f0 = torch.from_numpy(f0).float().to(self.device).unsqueeze(-1).unsqueeze(0)
        f0 = f0 * 2 ** (float(pitch_adjust) / 12)
        
        # extract volume
        volume_extractor = Volume_Extractor(hop_size)
        volume = volume_extractor.extract(audio)
        mask = (volume > 10 ** (float(self.threhold) / 20)).astype('float')
        mask = np.pad(mask, (4, 4), constant_values=(mask[0], mask[-1]))
        mask = np.array([np.max(mask[n : n + 9]) for n in range(len(mask) - 8)])
        mask = torch.from_numpy(mask).float().to(self.device).unsqueeze(-1).unsqueeze(0)
        mask = upsample(mask, self.args.data.block_size).squeeze(-1)
        volume = torch.from_numpy(volume).float().to(self.device).unsqueeze(-1).unsqueeze(0)

        # extract units
        audio_t = torch.from_numpy(audio).float().unsqueeze(0).to(self.device)
        units = self.units_encoder.encode(audio_t, sample_rate, hop_size)
        
        # spk_id or spk_mix_dict
        if self.enable_spk_id_cover:
            spk_id = self.spk_id
        else:
            spk_id = speaker_id
        spk_id = torch.LongTensor(np.array([[spk_id]])).to(self.device)
        
        # forward and return the output
        with torch.no_grad():
            output, _, (s_h, s_n) = self.model(units, f0, volume, spk_id = spk_id, spk_mix_dict = self.spk_mix_dict)
            output *= mask
            if self.vocoder_based_enhancer:
                output, output_sample_rate = self.enhancer.enhance(
                                                                output, 
                                                                self.args.data.sampling_rate, 
                                                                f0, 
                                                                self.args.data.block_size,
                                                                adaptive_key = self.enhancer_adaptive_key,
                                                                silence_front = silence_front)
            else:
                output_sample_rate = self.args.data.sampling_rate

            output = output.squeeze().cpu().numpy()
            return output, output_sample_rate


if __name__ == "__main__":
    #全局变量
    flag_vc=False#变声线程flag
    samplerate=44100#Hz
    block_time=1.5#s
    block_frame=0
    crossfade_frame=0
    crossfade_time=0.1#s
    fade_in_window=None#crossfade计算器
    fade_out_window=None
    f_safe_prefix_pad_length:float = 1.0
    input_wav:np.ndarray=None
    output_wav:np.ndarray=None
    temp_wav:np.ndarray=None
    f_pitch_change = 0#float(request_form.get("fPitchChange", 0))
    crossfade_last:np.ndarray=None#保存上一个output的crossfade
    f0_mode=["parselmouth", "dio", "harvest", "crepe"]
    input_devices,output_devices,input_device_indices, output_device_indices=get_devices()
    sg_model=sg.Input(key='sg_model',default_text='exp\\model_chino.pt')
    '''gui组件'''
    sg_input_device=sg.Combo(input_devices,key='sg_input_device',default_value=input_devices[sd.default.device[0]])
    sg_output_device=sg.Combo(output_devices,key='sg_output_device',default_value=output_devices[sd.default.device[1]])
    sg_noise=sg.Slider(range=(-60,0),orientation='h',key='noise',resolution=1,default_value=-35)
    sg_block=sg.Slider(range=(0.1,3.0),orientation='h',key='block',resolution=0.05,default_value=0.5)
    sg_pitch=sg.Slider(range=(-24,24),orientation='h',key='pitch',resolution=1,default_value=12)
    sg_crossfade=sg.Slider(range=(0.02,0.1),orientation='h',key='crossfade',resolution=0.01)
    sg_buffer_num=sg.Slider(range=(1,10),orientation='h',key='buffernum',resolution=1,default_value=1)
    sg_f0mode=sg.Combo(values=f0_mode,key='f0_mode',default_value=f0_mode[2])
    sg_samplerate=sg.Input(key='samplerate',default_text='44100')
    checkpoint_path=""
    # ddsp-svc下只需传入下列参数。
    # 对接的是串串香火锅大佬https://github.com/zhaohui8969/VST_NetProcess-。建议使用最新版本。
    # flask部分来自diffsvc小狼大佬编写的代码。
    # config和模型得同一目录。
    # 是否使用预训练的基于声码器的增强器增强输出，但对硬件要求更高。
    use_vocoder_based_enhancer = True
    enhancer_adaptive_key = 0
    select_pitch_extractor = f0_mode[2]
    # f0范围限制(Hz)
    limit_f0_min = 50
    limit_f0_max = 1100
    # 音量响应阈值(dB)
    threhold = -60
    # 默认说话人。
    spk_id = 1
    enable_spk_id_cover = True
    # 混合说话人字典（捏音色功能）
    # 设置为非 None 字典会覆盖 spk_id
    spk_mix_dict = None # {1:0.5, 2:0.5} 表示1号说话人和2号说话人的音色按照0.5:0.5的比例混合
    svc_model = None#SvcDDSP(checkpoint_path, use_vocoder_based_enhancer, enhancer_adaptive_key, select_pitch_extractor,limit_f0_min, limit_f0_max, threhold, spk_id, spk_mix_dict, enable_spk_id_cover)
    launcher()#start