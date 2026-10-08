"""Print the default microphone and the loopback device for the default speakers."""
import pyaudiowpatch as pyaudio

p = pyaudio.PyAudio()
try:
    mic = p.get_default_input_device_info()
    print("MIC     :", mic["name"], "|", int(mic["defaultSampleRate"]), "Hz |", mic["maxInputChannels"], "ch")
except OSError as e:
    print("MIC     : none found -", e)
try:
    loop = p.get_default_wasapi_loopback()
    print("SPEAKERS:", loop["name"], "|", int(loop["defaultSampleRate"]), "Hz |", loop["maxInputChannels"], "ch")
except Exception as e:
    print("SPEAKERS: no loopback device -", e)
p.terminate()
