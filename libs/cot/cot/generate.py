import datetime
import json
import os
import pkgutil
import time

import datasets as ds
import openai

# disable transformation (e.g. map) caching
# https://huggingface.co/docs/datasets/v2.6.1/en/package_reference/main_classes#datasets.disable_caching
ds.disable_caching()

TEMPLATES = json.loads(pkgutil.get_data(__name__, "templates.json"))

# Load your API key from an environment variable or secret management service
openai.api_key = os.getenv("OPENAI_API_KEY")


def print_now(return_flag=0):
    """
    It takes a flag as an argument and prints the current time in a specific format

    :param return_flag: 0 = print, 1 = return, defaults to 0 (optional)
    :return: the current time in the format of 'YYYY/MM/DD HH:MM:SS'
    """
    now = datetime.datetime.now()
    now = now.strftime("%Y/%m/%d %H:%M:%S")
    if return_flag == 0:
        print(now)
    elif return_flag == 1:
        return now
    else:
        pass





def generate_and_extract(data, config):
    """
    It takes a dataset and a config and generates cots for each example and extract answers.

    :param data: Dataset/DatasetDict - the dataset you want to generate CoTs for and extract answers
    :param config: a dictionary with the following keys:
        "idx_range": tuple(int,int) - Determines which indices the generate_and_extract routine is applied to,
            Default: None (All items are used)
        "debug": bool - Determines whether the openai api is called or a mock is returned, used for debugging,
            Default: True (openai api is not used)
        "instruction_keys": list(str) - Determines which instructions are used from templates.json,
            Default: None (All used)
        "cot_trigger_keys": list(str) - Determines which cot triggers are used from templates.json,
            Default: None (All are used)
        "answer_extraction_keys": list(str) - Determines which answer extraction prompts are used from templates.json,
            Default: None (All are used)
        "author" : str - Name of the person responsible for generation, Default: ""
        "engine": str -  Name of the openai engine used, Default: "text-davinci-002"
        "temperature": float - Name of the person responsible for generation, Default: 0
        "max_tokens": int - Maximum lenght of output generated by openai, Default: 128
        "api_time_interval": float - Pause between two api calls in seconds, Default: 1.0
        "warn": bool - Print warnings preventing excessive api usage, Default: True
    :return: the dataset with generated cots and extracted answers
    """

    ds.disable_caching()

    if "instruction_keys" not in config or not config["instruction_keys"]:
        config["instruction_keys"] = [None] + list(TEMPLATES["instructions"].keys())
    if "cot_trigger_keys" not in config or not config["cot_trigger_keys"]:
        config["cot_trigger_keys"] = list(TEMPLATES["cot-triggers"].keys())
    if "answer_extraction_keys" not in config or not config["answer_extraction_keys"]:
        config["answer_extraction_keys"] = list(TEMPLATES["answer-extractions"].keys())

    # Inserts None at index 0 of instruction_keys to query without an explicit instruction
    # Now it is asserted that there is at least one generation without an instruction
    # TODO maybe add option to disable this?
    # TODO maybe rethink this
    if None not in config["instruction_keys"]:
        config["instruction_keys"].insert(0, None)

    if isinstance(data, ds.arrow_dataset.Dataset):
        if "idx_range" in config and config["idx_range"] is not None:
            n_samples = config["idx_range"][1] - config["idx_range"][0]
        else:
            n_samples = len(data)
    elif isinstance(data, ds.dataset_dict.DatasetDict):
        if "idx_range" in config and config["idx_range"] is not None:
            n_samples = (config["idx_range"][1] - config["idx_range"][0]) * len(data)
        else:
            n_samples = sum([len(data[x]) for x in data])
    else:
        raise ValueError("Not recognized data")

    n_instruction_keys = len(config["instruction_keys"])
    n_cot_trigger_keys = len(config["cot_trigger_keys"])
    n_answer_extraction_keys = len(config["answer_extraction_keys"])

    n_total = (
        n_samples * n_instruction_keys * n_cot_trigger_keys
        + n_samples * n_instruction_keys * n_cot_trigger_keys * n_answer_extraction_keys
    )

    warn = True if "warn" not in config else config["warn"]
    if warn:
        warning = "You are about to call the openai API which produces costs.\n"
        warning += (
            f"Due to your settings you are about to call the openai API in total {n_total} times."
            + "\n"
        )
        warning += (
            "Number API calls for CoT generation: n_samples * n_instruction_keys * n_cot_trigger_keys"
            + "\n"
        )
        warning += (
            "Number API calls for answer extraction: n_samples * n_instruction_keys * n_cot_trigger_keys * n_answer_extraction_keys"
            + "\n"
        )
        warning += "Do you want to continue? y/n\n"
        print(warning)
        ans = input()
        if ans.lower() == "y":
            pass
        else:
            return
    return data.map(_generate_and_extract, with_indices=True, fn_kwargs=config)


def _generate_and_extract(
    item,
    idx,
    idx_range=None,
    author="",
    engine="text-davinci-002",
    temperature=0,
    max_tokens=128,
    api_time_interval=1.0,
    instruction_keys=None,
    cot_trigger_keys=None,
    answer_extraction_keys=None,
    debug=True,
    verbose=False,
):
    """
    The function takes in a JSON object (item) and generates a CoT (Chain-of-Thought) for each combination of
    of instructions and CoT triggers. For each generated CoT and for each of the given answer extractions it extracts an answer

    :param item: the item (example) of a dataset to be processed
    :param idx: the index of the item in the dataset
    :param idx_range: the range of indices to generate and extract for, if idx not within idx_range do nothing and return item
    :param author: the name of the person who generated the CoT
    :param engine: the GPT-3 engine to use, defaults to text-davinci-002 (optional)
    :param temperature: 0.0 means the model will output the most likely answer, 1.0 means the model will
    output the most random answer, defaults to 0 (optional)
    :param max_tokens: The maximum number of tokens to generate, defaults to 128 (optional)
    :param api_time_interval: The time interval between API calls
    :param instruction_keys: the instructions to generate the CoT
    :param cot_trigger_keys: the trigger to generate the CoT
    :param answer_extraction_keys: the trigger to extract answers given a generated CoT
    :param debug: If True, will print out the prompts and generated text, defaults to True (optional)
    :return: item populated with various fields
    """
    if idx_range is None or (idx >= idx_range[0] and idx < idx_range[1]):
        pass
    else:
        return item

    for instruction_key in instruction_keys:
        for cot_trigger_key in cot_trigger_keys:
            generated_cot = {
                "templates_version": TEMPLATES["version"],
                "instruction": instruction_key,
                "cot-trigger": cot_trigger_key,
                "cot": "",
                "answers": [],
                "author": author,
                "date": "",
                "model": {
                    "name": engine,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                "comment": "",
                "annotation": [],
            }
            template_version, generate_cot_prompt = get_cot_generation_prompt(
                item, instruction_key, cot_trigger_key
            )
            if verbose:
                print("\n-------------------COT TRIGGER-------------------")
            if verbose:
                print(generate_cot_prompt)
            cot = query_gpt3(
                generate_cot_prompt,
                engine,
                temperature,
                max_tokens,
                api_time_interval,
                debug,
            )
            if verbose:
                print("\n------------------GENERATED COT-------------------")
            if verbose:
                print(cot)
            generated_cot["cot"] = cot
            generated_cot["date"] = print_now(1)

            for answer_extraction_key in answer_extraction_keys:
                answer = {"answer-extraction": answer_extraction_key, "answer": "", "correct_answer": None}
                _, answer_extraction_prompt = get_answer_extraction_prompt(
                    item, cot, answer_extraction_key
                )
                if verbose:
                    print("\n------------------ANSWER EXTRACTION-------------------")
                if verbose:
                    print(answer_extraction_prompt)
                assert (
                    _ == template_version
                ), "Version mismatch cot trigger <-> answer extraction"
                predicted_answer = query_gpt3(
                    answer_extraction_prompt,
                    engine,
                    temperature,
                    max_tokens,
                    api_time_interval,
                    debug,
                )
                if verbose:
                    print("\n------------------EXTRACTED ANSWER-------------------")
                if verbose:
                    print(predicted_answer)
                answer["answer"] = predicted_answer
                generated_cot["answers"].append(answer)
            item["generated_cot"].append(generated_cot)

    return item


def get_cot_generation_prompt(item, instruction_key, cot_trigger_key):
    choices = "\n".join(
        [f"{chr(65+i)}) {example}" for i, example in enumerate(item["choices"])]
    )
    if instruction_key is not None:
        prompt = TEMPLATES["instructions"][instruction_key] + "\n\n"
    prompt = (
        item["question"]
        + "\n"
        + choices
        + "\n\n"
        + TEMPLATES["cot-triggers"][cot_trigger_key]
    )
    return TEMPLATES["version"], prompt


def get_answer_extraction_prompt(item, generated_cot, answer_extraction_key):
    choices = "\n".join(
        [f"{chr(65+i)}) {example}" for i, example in enumerate(item["choices"])]
    )
    prompt = (
        item["question"]
        + "\n"
        + choices
        + "\n\n"
        + generated_cot
        + "\n"
        + TEMPLATES["answer-extractions"][answer_extraction_key]
    )
    return TEMPLATES["version"], prompt


def query_gpt3(input, engine, temperature, max_tokens, api_time_interval, debug):
    if debug:
        return "test"
    else:
        # GPT-3 API allows each users execute the API within 60 times in a minute ...
        # time.sleep(1)
        time.sleep(api_time_interval)
        response = openai.Completion.create(
            engine=engine,
            prompt=input,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=None,
        )
        return response["choices"][0]["text"]
