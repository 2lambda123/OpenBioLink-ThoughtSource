import datetime
import json
import os
import pkgutil
import time
import uuid

import datasets as ds

# disable transformation (e.g. map) caching
# https://huggingface.co/docs/datasets/v2.6.1/en/package_reference/main_classes#datasets.disable_caching
ds.disable_caching()

TEMPLATES = json.loads(pkgutil.get_data(__name__, "templates.json"))


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
            Default: "all" (All items are used)
        "debug": bool - Determines whether the api is called or a mock is returned, used for debugging,
            Default: True (api is not used)
        "instruction_keys": list(str) - Determines which instruction_keys are used from templates.json,
            Default: "all" (All used)
        "cot_trigger_keys": list(str) - Determines which cot triggers are used from templates.json,
            Default: None (All are used)
        "answer_extraction_keys": list(str) - Determines which answer extraction prompts are used from templates.json,
            Default: None (All are used)
        "author" : str - Name of the person responsible for generation, Default: ""
        "api_service" str - Name of the used api service, Default: "openai"
        "engine": str -  Name of the engine used, Default: "text-davinci-002"
        "temperature": float - 0.0 means the model will output the most likely answer, 1.0 means the model will
            output the most random answer, defaults to 0 (optional)
        "max_tokens": int - Maximum lenght of output generated by model , Default: 128
        "api_time_interval": float - Pause between two api calls in seconds, Default: 1.0
        "warn": bool - Print warnings preventing excessive api usage, Default: True
    :return: the dataset with generated cots and extracted answers
    """

    ds.disable_caching()

    # Creating cofigurations for the options 'all' or 'None':
    keys = ["instruction_keys", "cot_trigger_keys", "answer_extraction_keys"]
    names_in_template = ["instructions", "cot-triggers", "answer-extractions"]
    for key, name in zip(keys, names_in_template):
        if key not in config or config[key] == "all":
            config[key] = [None] + list(TEMPLATES[name].keys())
        elif not config[key]:
            config[key] = [None]

    # Inserts None at index 0 of instruction_keys to query without an explicit instruction
    # TODO rethink this, maybe add option to disable this
    # for key in ["instruction_keys","cot_trigger_keys"]:
    #     if None not in config[key]:
    #         config[key].insert(0, None)

    if isinstance(data, ds.arrow_dataset.Dataset):
        features = data.info.features
        if "idx_range" in config and config["idx_range"] != "all":
            n_samples = config["idx_range"][1] - config["idx_range"][0]
        else:
            n_samples = len(data)
    elif isinstance(data, ds.dataset_dict.DatasetDict):
        features = data["train"].info.features
        if "idx_range" in config and config["idx_range"] != "all":
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
    debug = True if "debug" not in config else config["debug"]
    if warn:
        warning = f"""
            You are about to \033[1m call an external API \033[0m in total {n_total} times, which \033[1m may produce costs \033[0m.
            Number API calls for CoT generation: n_samples {n_samples} * n_instruction_keys {n_instruction_keys} * n_cot_trigger_keys {n_cot_trigger_keys}
            Number API calls for answer extraction: n_samples {n_samples} * n_instruction_keys {n_instruction_keys} * n_cot_trigger_keys {n_cot_trigger_keys} * n_answer_extraction_keys {n_answer_extraction_keys}
            Do you want to continue? y/n
            """
        if debug:
            warning += "\033[1m Note: You are in debug mode. When entering 'y', a test run without API calls is made. \033[0m"
        print(warning)
        ans = input()
        if ans.lower() == "y":
            pass
        else:
            return
    return data.map(_generate_and_extract, with_indices=True, fn_kwargs=config, features=features)


def _generate_and_extract(
    item,
    idx,
    idx_range="all",
    author="",
    api_service="openai",
    engine="text-davinci-002",
    temperature=0,
    max_tokens=128,
    api_time_interval=1.0,
    instruction_keys="all",
    cot_trigger_keys="all",
    answer_extraction_keys="all",
    debug=True,
    warn=True,
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

    if idx_range == "all" or (idx >= idx_range[0] and idx < idx_range[1]):
        pass
    else:
        return item

    # Adding Letters (A,B,C,...) for the given multiple choice answers.
    answer_choices_letters = "\n".join(
        [f"{chr(65+i)}) {example}" for i, example in enumerate(item["choices"])]
    )

    prompt = item["question"] + "\n" + answer_choices_letters + "\n\n"

    for instruction_key in instruction_keys:

        if instruction_key is not None:
            instruction_promt = (
                TEMPLATES["instructions"][instruction_key] + "\n\n" + prompt
            )
        else:
            instruction_promt = prompt

        for cot_trigger_key in cot_trigger_keys:
            generated_cot = {
                "id": str(uuid.uuid4()),
                "templates_version": TEMPLATES["version"],
                "instruction": instruction_key,
                "cot-trigger": cot_trigger_key,
                "prompt_text": "",
                "cot": "",
                "answers": [],
                "author": author,
                "date": "",
                "api_service": api_service,
                "model": str({
                    "name": engine,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }),
                "comment": "",
                "annotation": [],
            }

            if cot_trigger_key is not None:
                generate_cot_prompt = (
                    instruction_promt
                    + TEMPLATES["cot-triggers"][cot_trigger_key]
                    + "\n"
                )
            else:
                generate_cot_prompt = instruction_promt

            if verbose:
                print("\n-------------------COT TRIGGER-------------------")
                print(generate_cot_prompt)

            cot = query_model(
                generate_cot_prompt,
                api_service,
                engine,
                temperature,
                max_tokens,
                api_time_interval,
                debug,
            )
            if verbose:
                print("\n------------------GENERATED COT-------------------")
                print(cot)

            generated_cot["cot"] = cot
            generated_cot["prompt_text"] = generate_cot_prompt
            generated_cot["date"] = print_now(1)

            for answer_extraction_key in answer_extraction_keys:
                if answer_extraction_key is None:
                    pass

                else:
                    answer = {
                        "id": str(uuid.uuid4()),
                        "answer-extraction": answer_extraction_key,
                        "answer_extraction_text": "",
                        "answer": "",
                        "correct_answer": None,
                    }

                    answer_extraction_prompt = (
                        generate_cot_prompt
                        + cot
                        + "\n"
                        + TEMPLATES["answer-extractions"][answer_extraction_key]
                        + "\n"
                    )
                    if verbose:
                        print(
                            "\n------------------ANSWER EXTRACTION-------------------"
                        )
                        print(answer_extraction_prompt)

                    predicted_answer = query_model(
                        answer_extraction_prompt,
                        api_service,
                        engine,
                        temperature,
                        max_tokens,
                        api_time_interval,
                        debug,
                    )
                    if verbose:
                        print("\n------------------EXTRACTED ANSWER-------------------")
                        print(predicted_answer)

                    answer["answer"] = predicted_answer
                    answer["answer_extraction_text"] = answer_extraction_prompt
                    generated_cot["answers"].append(answer)
            item["generated_cot"].append(generated_cot)

    return item


def query_model(
    input, api_service, engine, temperature, max_tokens, api_time_interval, debug
):
    if debug:
        return "test"

    # lanchain package implementation
    else:
        from langchain import LLMChain, Prompt

        time.sleep(api_time_interval)
        # This script produces prompts as strings, but the langchain package requires
        # Prompt objects, so here is a fake object created with the foo variable "empty"
        template = "{prompt}"
        prompt = Prompt(template=template, input_variables=["prompt"])

        if api_service == "openai":
            from langchain import OpenAI

            llm_chain = LLMChain(
                prompt=prompt,
                llm=OpenAI(
                    model_name=engine,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
        if api_service == "huggingface_hub":
            from langchain import HuggingFaceHub

            llm_chain = LLMChain(
                prompt=prompt,
                llm=HuggingFaceHub(
                    repo_id=engine,
                    # parameter options: https://huggingface.co/docs/api-inference/detailed_parameters
                    model_kwargs={"temperature": temperature, "max_length": max_tokens},
                ),
            )
        response = llm_chain.predict(prompt=input, stop=None)
        return response
