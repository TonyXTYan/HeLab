from openai import OpenAI
import openai
import time
import os
import argparse

client = OpenAI(
    # base_url="http://150.203.177.251:1234/v1/",
    # base_url = "http://192.168.1.39:1234/v1/",
    base_url="http://192.168.1.171:1234/v1/",
    # base_url = "https://kg2ttl3v-1234.aue.devtunnels.ms/v1/",
    # base_url = "https://45kzmdx4-1234.aue.devtunnels.ms/v1/",
    # base_url = "https://45kzmdx4-1235.aue.devtunnels.ms/v1/",
    # base_url = "https://45kzmdx4-80.aue.devtunnels.ms/v1/",
    api_key="lmstudio",
)


def list_available_models():
    models = client.models.list()
    return [model.id for model in models]
print("Available models:")
print(list_available_models())
print("")

def ask_model(question: str):
    response = client.completions.create(
        # model="qwen2.5-coder-7b-instruct",
        # model="qwen2.5-coder-14b-instruct",
        model="qwen2.5-coder-32b-instruct",
        prompt=question,
        # max_tokens=16384
        max_tokens=65536
    )
    return response.choices[0].text.strip()


def read_files_from_paths(paths):
    combined_content = ""
    for path in paths:
        if os.path.exists(path):
            with open(path, 'r') as file:
                combined_content += file.read() + "\n"
        else:
            print(f"Path {path} does not exist.")
    return combined_content

# def review_files(paths, system_message):
#     combined_content = read_files_from_paths(paths)
def review_files(target_file, context_files, system_message):
    target_content = read_files_from_paths([target_file])
    context_content = read_files_from_paths(context_files)
    combined_content = f"Target file: {target_file}\n\n{target_content}\n\nContext files: {context_files}\n\n{context_content}"
    # system_message = "You are a LaTeX writing assistant. Please provide a summary list of suggestions to improve the content of the combined files."
    # system_message = "You are a LaTeX writing assistant. Please rewrite the content of the combined files with improved clarity and coherence."
    start_time = time.time()
    response = client.chat.completions.create(
        # model="qwen2.5-coder-7b-instruct",
        # model="qwen2.5-coder-14b-instruct",
        model="qwen2.5-coder-32b-instruct",
        messages=[
            # {"role": "system", "content": "You are an assistant proficient in processing LaTeX documents."},
            {"role": "system", "content": system_message},
            # {"role": "user", "content": "summarize the content of the combined files in three sentences"},
            {"role": "user", "content": combined_content},
        ],
        # max_tokens=20000,
        max_tokens=65536,
        stream=True,
        frequency_penalty=1.0,
        presence_penalty=1.0,
        stream_options={"include_usage": True},
        timeout=1200,
    )

    collected_messages = []
    total_chars = 0
    for chunk in response:
        # print(chunk)
        if chunk.choices is None:
            print(chunk.event)
            print(chunk.data)
            continue
        chunk_message = chunk.choices[0].delta.content
        if chunk_message:
            collected_messages.append(chunk_message)
            print(chunk_message, end='')  # Print each chunk as it is received
        if chunk_message == 'END OF CONVERSATION':
            break
        if chunk.choices[0].finish_reason == 'length':
            break
        if chunk.choices[0].finish_reason == 'stop':
            break
        total_chars += len(chunk_message)

    end_time = time.time()
    elapsed_time = end_time - start_time
    chars_per_sec = total_chars / elapsed_time if elapsed_time > 0 else 0

    return ''.join(collected_messages), response, elapsed_time, total_chars, chars_per_sec

STR_NEW = "  ====  Starting a new conversation ====================================================\n"
STR_END = "  ====  End of conversation  ===========================================================\n"
if __name__ == "__main__":
    default_system_message = (""
        "You are a LaTeX writing assistant. "
        # "Rewrite the following .tex files with improved clarity and coherence. "
        "Only output the rewritten content of the target file."
        "Do not output content from the context files."
        # "Please provide a summary list of suggestions to improve the content of the combined files. "
        "Please rewrite the content of the combined files with improved clarity and coherence."
        "You have to write this  to production quality LaTeX code."
        "do not include any comments or commands in the output." 
        "And attempt to continue writing additional content as much as possible"
    )
    parser = argparse.ArgumentParser(description="Review LaTeX files using OpenAI API")
    parser.add_argument('target_file', nargs='?',
                        default="/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/he44.tex",  
                        help="Path to the LaTeX file to be reviewed"
                        )
    parser.add_argument('context_filess', nargs='*',
                        default=[
                            # "/Users/tonyyan/Documents/_ANU/_PhD_Thesis/main.tex",
                            "/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/introduction.tex",
                            # "/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/he44.tex",
                            "/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/he34.tex",
                            "/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/csl.tex",
                        ],
                        help="Paths to the LaTeX files to be reviewed"
                        )
    parser.add_argument('system_message', nargs='?',
                        default=default_system_message,
                        help="System message for the OpenAI model"
                        )

    args = parser.parse_args()
    # message, response, elapsed_time, total_chars, chars_per_sec = review_files(args.paths, args.system_message)
    # print(message)
    sys_total_chars = 0
    iteration = 0
    while True:
        print(STR_NEW)
        print("\n\n\n")
        time.sleep(0.1)
        message, response, elapsed_time, total_chars, chars_per_sec = review_files(args.target_file, args.context_filess, args.system_message)
        sys_total_chars += total_chars
        iteration += 1
        print("\n\n\n")
        print(STR_END)
        print(f"Generated chars: {total_chars} in {elapsed_time:.2f}sec, "+
              f"{chars_per_sec:.2f} chars/s, iteration: {iteration}, total chars: {sys_total_chars}")
        print("\n\n\n")

        os.makedirs("/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/.llm/", exist_ok=True)
        output_filename = "combined"
        with open(f"/Users/tonyyan/Documents/_ANU/_PhD_Thesis/chapters/.llm/{output_filename}.llm-{iteration}.tex", "w") as file:
            file.write(message)
        time.sleep(0.1)
        
        














