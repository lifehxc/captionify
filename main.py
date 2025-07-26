import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel, Text, Scrollbar, colorchooser
import whisper
import ffmpeg
from pathlib import Path
import os
import threading
from googletrans import Translator
import vlc
import subprocess

LANGUAGES = {
    'English': 'en',
    'French': 'fr',
    'Spanish': 'es',
    'German': 'de',
    'Italian': 'it',
    'Portuguese': 'pt',
    'Chinese (Simplified)': 'zh-cn',
    'Japanese': 'ja',
    'Russian': 'ru',
    'Arabic': 'ar',
    'Hindi': 'hi'
}

FONT_SIZES = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32]
FONT_FAMILIES = [
    "Arial", "DejaVu Sans", "Liberation Sans", "Helvetica",
    "Times New Roman", "Courier New", "Verdana"
]

def transcribe_audio(video_path, model_size="base"):
    model = whisper.load_model(model_size)
    result = model.transcribe(video_path)
    return result['text'], result['segments']

def translate_segments(segments, target_language):
    translator = Translator()
    for seg in segments:
        translated = translator.translate(seg['text'], dest=target_language)
        seg['translated'] = translated.text
    return segments

def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def save_srt(segments, srt_path):
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments):
            f.write(f"{i+1}\n")
            f.write(f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
            f.write(f"{seg['translated'].strip()}\n\n")

def hex_to_ass_color(hex_color):
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return f"&H00{hex_color[4:6]}{hex_color[2:4]}{hex_color[0:2]}&"
    return "&H00000000&"

def create_subtitled_video(
    video_path, srt_path, output_path, font_size=24, mask_color="#000000",
    subtitle_position="bottom", box_height=None, box_offset=0, font_family="Arial",
    font_color="#FFFFFF", border_color="#000000", outline=2
):
    ffmpeg_color = mask_color.replace("#", "0x")
    if box_height is None:
        box_height = int(font_size * 2.2)

    # Always align subtitle vertical center to the mask band
    if subtitle_position == "bottom":
        y_base = f"ih-{box_height + 20}"
        alignment = 2
        offset = -abs(box_offset)
    elif subtitle_position == "top":
        y_base = "0"
        alignment = 6
        offset = abs(box_offset)
    else:  # center
        y_base = f"(ih-{box_height})/2"
        alignment = 8
        offset = box_offset

    y_expr = f"({y_base})+{offset}" if offset else y_base

    drawbox = f"drawbox=x=0:y={y_expr}:w=iw:h={box_height}:color={ffmpeg_color}@1:t=fill"

    # Center the text vertically in the mask band
    margin_lr = 40
    margin_v = max(10, (box_height - font_size) // 2)

    force_style = (
        f"Fontname={font_family},Fontsize={font_size},Alignment={alignment},"
        f"PrimaryColour={hex_to_ass_color(font_color)},"
        f"OutlineColour={hex_to_ass_color(border_color)},"
        f"Outline={outline},MarginV={margin_v},MarginL={margin_lr},MarginR={margin_lr}"
    )
    subtitles = f"subtitles='{srt_path}':force_style='{force_style}'"

    try:
        (
            ffmpeg.input(video_path)
            .output(
                output_path,
                vf=f"{drawbox},{subtitles}",
                acodec='copy'
            )
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        print("FFmpeg stderr:", e.stderr.decode())
        messagebox.showerror("FFmpeg error", e.stderr.decode())
        raise

def play_video(video_path):
    def _run():
        try:
            instance = vlc.Instance()
            player = instance.media_player_new()
            media = instance.media_new(video_path)
            player.set_media(media)
            player.play()
        except Exception as e:
            print("VLC Error:", e)
    threading.Thread(target=_run, daemon=True).start()

def preview_video_window(video_path, srt_path, after_preview_callback):
    top = Toplevel(root)
    top.title("Preview and Mask Settings")
    top.geometry("1000x750")
    top.transient(root)
    top.grab_set()

    embed_frame = tk.Frame(top, height=350)
    embed_frame.pack(fill=tk.BOTH, expand=True)

    # Option variables
    subtitle_position_var = tk.StringVar(value="bottom")
    mask_color_var = tk.StringVar(value="#000000")
    font_size_var = tk.IntVar(value=16)
    box_height_var = tk.IntVar(value=60)
    box_offset_var = tk.IntVar(value=0)
    font_family_var = tk.StringVar(value=FONT_FAMILIES[0])
    font_color_var = tk.StringVar(value="#FFFFFF")
    border_color_var = tk.StringVar(value="#000000")
    outline_var = tk.IntVar(value=2)

    # Horizontal frame for options
    options_frame = tk.Frame(top)
    options_frame.pack(pady=10, fill=tk.X)

    # Position
    tk.Label(options_frame, text="Position:").grid(row=0, column=0, padx=5)
    tk.OptionMenu(options_frame, subtitle_position_var, "top", "center", "bottom").grid(row=0, column=1, padx=5)

    # Mask color
    tk.Label(options_frame, text="Mask:").grid(row=0, column=2, padx=5)
    def choose_mask_color():
        color_code = colorchooser.askcolor(title="Mask Color")[1]
        if color_code:
            mask_color_var.set(color_code)
        top.lift()
    tk.Button(options_frame, text="Color", command=choose_mask_color).grid(row=0, column=3, padx=5)

    # Font family
    tk.Label(options_frame, text="Font:").grid(row=0, column=4, padx=5)
    tk.OptionMenu(options_frame, font_family_var, *FONT_FAMILIES).grid(row=0, column=5, padx=5)

    # Font size
    tk.Label(options_frame, text="Size:").grid(row=0, column=6, padx=5)
    tk.OptionMenu(options_frame, font_size_var, *FONT_SIZES).grid(row=0, column=7, padx=5)

    # Font color
    tk.Label(options_frame, text="Text:").grid(row=0, column=8, padx=5)
    def choose_font_color():
        color_code = colorchooser.askcolor(title="Text Color")[1]
        if color_code:
            font_color_var.set(color_code)
        top.lift()
    tk.Button(options_frame, text="Color", command=choose_font_color).grid(row=0, column=9, padx=5)

    # Border color
    tk.Label(options_frame, text="Border:").grid(row=0, column=10, padx=5)
    def choose_border_color():
        color_code = colorchooser.askcolor(title="Border Color")[1]
        if color_code:
            border_color_var.set(color_code)
        top.lift()
    tk.Button(options_frame, text="Color", command=choose_border_color).grid(row=0, column=11, padx=5)

    # Outline thickness
    tk.Label(options_frame, text="Outline:").grid(row=0, column=12, padx=5)
    tk.Scale(options_frame, from_=0, to=10, orient=tk.HORIZONTAL, variable=outline_var, width=8, length=80).grid(row=0, column=13, padx=5)

    # Sliders for mask height and offset
    sliders_frame = tk.Frame(top)
    sliders_frame.pack(pady=5, fill=tk.X)
    tk.Label(sliders_frame, text="Mask Height:").grid(row=0, column=0, padx=5)
    tk.Scale(sliders_frame, from_=20, to=600, orient=tk.HORIZONTAL, variable=box_height_var, length=200).grid(row=0, column=1, padx=5)
    tk.Label(sliders_frame, text="Vertical Offset:").grid(row=0, column=2, padx=5)
    tk.Scale(sliders_frame, from_=-300, to=300, orient=tk.HORIZONTAL, variable=box_offset_var, length=200).grid(row=0, column=3, padx=5)

    preview_temp = os.path.join(os.path.dirname(srt_path), "preview_temp.mp4")
    preview_player = {"player": None}

    def render_preview():
        if preview_player["player"]:
            preview_player["player"].stop()
        try:
            create_subtitled_video(
                video_path, srt_path, preview_temp,
                font_size=font_size_var.get(),
                mask_color=mask_color_var.get(),
                subtitle_position=subtitle_position_var.get(),
                box_height=box_height_var.get(),
                box_offset=box_offset_var.get(),
                font_family=font_family_var.get(),
                font_color=font_color_var.get(),
                border_color=border_color_var.get(),
                outline=outline_var.get()
            )
        except Exception as e:
            messagebox.showerror("Error", f"Error generating preview: {e}")
            return
        def _run():
            try:
                instance = vlc.Instance()
                player = instance.media_player_new()
                media = instance.media_new(preview_temp)
                player.set_media(media)
                embed_frame.update()  # <-- Important: force update before set_xwindow
                player.set_xwindow(embed_frame.winfo_id())
                player.set_fullscreen(False)  # <-- Force windowed mode
                player.play()
                preview_player["player"] = player
            except Exception as e:
                print("VLC Error:", e)
        threading.Thread(target=_run, daemon=True).start()

    tk.Button(top, text="Preview", command=render_preview).pack(pady=10)

    def validate_and_preview():
        if preview_player["player"]:
            preview_player["player"].stop()
        after_preview_callback(
            mask_color_var.get(),
            font_size_var.get(),
            subtitle_position_var.get(),
            box_height_var.get(),
            box_offset_var.get(),
            font_family_var.get(),
            font_color_var.get(),
            border_color_var.get(),
            outline_var.get()
        )
        if os.path.exists(preview_temp):
            os.remove(preview_temp)
        top.destroy()

    tk.Button(top, text="Validate and Continue", command=validate_and_preview).pack(pady=20)
    render_preview()

def edit_subtitles_window(segments, callback):
    def validate_and_close():
        edited_text = text_box.get("1.0", tk.END).strip()
        edited_blocks = [block.strip() for block in edited_text.split('\n\n') if block.strip()]
        for i, block in enumerate(edited_blocks):
            try:
                lines = block.split('\n')
                segments[i]['translated'] = lines[2]
            except IndexError:
                continue
        callback()
        top.destroy()

    top = Toplevel(root)
    top.title("Edit Translated Subtitles")
    top.geometry("600x500")
    top.transient(root)
    top.grab_set()

    text_frame = tk.Frame(top)
    text_frame.pack(fill=tk.BOTH, expand=True)

    text_box = Text(text_frame, wrap=tk.WORD)
    text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    scroll = Scrollbar(text_frame, command=text_box.yview)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text_box.config(yscrollcommand=scroll.set)

    for i, seg in enumerate(segments):
        text_box.insert(tk.END, f"{i+1}\n")
        text_box.insert(tk.END, f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
        text_box.insert(tk.END, f"{seg.get('translated', seg['text'])}\n\n")

    button_frame = tk.Frame(top)
    button_frame.pack(fill=tk.X, pady=5)

    tk.Button(button_frame, text="Validate and Continue", command=validate_and_close).pack(side=tk.LEFT, padx=10)
    tk.Button(button_frame, text="Cancel", command=top.destroy).pack(side=tk.RIGHT, padx=10)

def process_video():
    video_path = filedialog.askopenfilename(title="Select a video", filetypes=[("Video files", "*.mp4 *.mov *.avi")])
    if not video_path:
        return

    target_language = LANGUAGES[selected_lang.get()]

    try:
        _, segments = transcribe_audio(video_path)
        translate_segments(segments, target_language)

        def after_edit():
            output_dir = filedialog.askdirectory(title="Select output folder")
            if not output_dir:
                return

            base = Path(video_path).stem
            srt_path = os.path.join(output_dir, f"{base}.srt")
            output_video = os.path.join(output_dir, f"{base}_subtitled.mp4")

            save_srt(segments, srt_path)

            def after_preview(mask_color, font_size, subtitle_position, box_height, box_offset, font_family, font_color, border_color, outline):
                create_subtitled_video(
                    video_path, srt_path, output_video,
                    font_size, mask_color, subtitle_position, box_height, box_offset, font_family, font_color, border_color, outline
                )
                messagebox.showinfo("Success", f"Video saved at:\n{output_video}")
                play_video(output_video)

            preview_video_window(video_path, srt_path, after_preview)

        edit_subtitles_window(segments, after_edit)

    except Exception as e:
        messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Subtitle Generator")
    root.geometry("400x400")

    tk.Label(root, text="Target Language:").pack()
    selected_lang = tk.StringVar(root)
    selected_lang.set("English")
    tk.OptionMenu(root, selected_lang, *LANGUAGES.keys()).pack(pady=5)
    tk.Button(root, text="Select Video and Generate Subtitles", command=process_video).pack(pady=20)
    root.mainloop()
