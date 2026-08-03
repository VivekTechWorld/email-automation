# How Our Email Robot Works (Explained for a 10-Year-Old! 🚀)

Imagine you have a super-smart robot helper. People send you emails, and this robot reads them, decides how important they are, and writes back. This document explains exactly how it works, step by step, and how we teach the robot to be smart.

---

## Part 1: The Journey of an Email 💌

When someone sends an email, our system sends a secret message behind the scenes. It looks like this:
`curl -X POST http://localhost:8000/process-email`

Think of `curl` as a mail carrier knocking on our digital door.

### 1. The Receptionist (`backend/main.py`)
When the mail carrier knocks, our Receptionist answers. The Receptionist is a tool called **FastAPI**.
* **What happens:** The `process_email` function in `main.py` takes the email. It looks at who sent it and what the subject is. 
* **The Code:** `sender_email = extract_email_address(email.sender)`
* **Next Step:** The Receptionist hands the email to the Brain room by calling `process_email_combined()`.

### 2. The Brain's First Try (`backend/generator.py`)
Now we are inside `generator.py`. This is where the AI lives! We use a tool called **Ollama**, which is like an engine that runs our AI robot locally on our computer.

* **What happens:** We give the robot a **Prompt** (a set of instructions). We tell it: *"Read this email. Tell me what category it is, how severe it is, and write a reply."*
* **JSON Magic:** We ask the robot to give the answer in **JSON**. JSON is just a super organized checklist. Instead of writing a messy paragraph, the robot fills out boxes:
  * Box 1: Category (Is it a bug? A sales question?)
  * Box 2: Severity (Is it normal? Or a critical emergency?)
  * Box 3: Confidence (How sure are you? 1 to 5)
  * Box 4: Response (The actual reply text)
* **What if the robot messes up?** Sometimes robots write broken JSON (like forgetting to close a bracket `}`). Our code has special rules to fix the broken brackets automatically!

### 3. The Open-Book Test: RAG (Retrieval-Augmented Generation)
What if the customer asks a really hard question, and the robot's "Confidence" is low? Or what if it doesn't know the answer?

* **The Condition Check:** In the code, we check: `if needs_rag:` (which means, does the robot need help?).
* **AI Concept - What is RAG?** RAG stands for Retrieval-Augmented Generation. Imagine giving a student a test. RAG is like letting them use an open book. If the robot doesn't know the answer, we search our `chroma_db` (a massive digital library of our instruction manuals). We pull out the exact manual page and tell the robot: *"Read this page, THEN answer the email."*

### 4. The Final Polish (`clean_response`)
Sometimes the robot gets too chatty and writes weird things like *"--- KNOWLEDGE BASE ---"* or hallucinates greetings like *"Dear Unhappy Customer"*. 
* The `clean_response` function acts like an editor. It deletes weird robot-speak and makes sure the email starts with a friendly "Hi,".

### 5. Sending it Back (`main.py`)
We go back to the Receptionist in `main.py`. 
* **The Condition Check:** `if severity == "critical":`
* If the robot marked the email as "critical" (like the server being down), the Receptionist panics (in a good way!). Instead of just replying, it creates an **Alert** and sends a special warning email straight to the human boss (`realParthiv@gmail.com`). 
* If it's normal, it just sends the nice reply back to the customer.

---

## Part 2: How We Teach the Robot (Fine-Tuning) 🧠

Before the robot can be smart, it has to go to school! This happens in the `finetune/finetune_7b.py` file. Fine-tuning means taking a robot that already knows how to speak English, and teaching it our specific company rules.

### Explaining the Tools (The Imports)
At the top of the file, we pack the robot's backpack with tools:
* `import json`: A tool to read the organized checklists.
* `import os`, `sys`, `Path`: Tools to navigate the computer's folders to find the homework files.
* `import torch`: The heavy-duty math calculator. AI is just a loooooot of math!
* `from transformers import ...`: Transformers are the modern type of AI brains. This library lets us download and use big brains.
  * `AutoTokenizer`: **AI Concept - Tokenizer.** Computers don't read words. They read numbers. A Tokenizer is a word-chopper. It chops "Hello world" into little pieces (tokens) like "He", "llo", "world" and turns them into numbers.
  * `AutoModelForCausalLM`: This is the actual AI brain that guesses the next word in a sentence.
* `from peft import LoraConfig`: **AI Concept - LoRA.** LoRA stands for Low-Rank Adaptation. Imagine the AI brain is a giant, heavy textbook with billions of pages. To teach it something new, rewriting the whole book would take a supercomputer and months of time. LoRA is a brilliant trick: instead of rewriting the book, we just stick **sticky notes** on the pages! It's much faster and requires way less computer memory (RAM).
* `from datasets import Dataset`: This is the binder holding all the study flashcards.

### Explaining the Parameters (The Lesson Plan)
When we set up the school, we use these settings:

* `BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"`: This is the starting brain. "7B" means it has 7 Billion connections (synapses, like a tiny brain).
* `LORA_RANK = 8` & `LORA_ALPHA = 16`: These decide how big our "sticky notes" are. A rank of 8 means we are using very small sticky notes to save memory.
* `EPOCHS = 5`: **AI Concept - Epoch.** An epoch is reading the entire study book from front to back. 5 epochs means the robot will read the study book 5 times to memorize it.
* `BATCH_SIZE = 1`: **AI Concept - Batch Size.** How many flashcards should the robot look at exactly at the same time? We set it to 1 because looking at more would make our computer run out of memory and crash.
* `GRAD_ACCUM = 4`: **AI Concept - Gradient Accumulation.** Since we can only look at 1 flashcard at a time, we tell the robot: "Look at 4 flashcards one by one, remember the lessons, and THEN update your brain." This fakes a bigger batch size!
* `LEARNING_RATE = 1e-4` (which means 0.0001): **AI Concept - Learning Rate.** When the robot makes a mistake, it adjusts its brain. If the learning rate is too big, the robot jumps to conclusions and forgets everything. If it's too small, it takes forever to learn. 0.0001 is a nice, slow, careful baby step.
* `optim="adafactor"`: **AI Concept - Optimizer.** The optimizer is the teacher grading the test and telling the robot how to fix its mistakes. We use "adafactor" because it is a special teacher that uses half as much computer memory as other teachers!

### The Training Process
1. We load the Tokenizer (word-chopper).
2. We load the model in `bfloat16`. (Normally numbers take up a lot of space. `bfloat16` cuts the numbers in half to save 50% of the computer's memory!).
3. We put on the LoRA sticky notes.
4. We chop up all our training emails into numbers.
5. The `Trainer` takes over, makes the robot read the emails 5 times (`Epochs`), checks its answers, and updates the sticky notes.
6. Finally, we save the sticky notes (`final_weights`) to the computer so we can use them tomorrow!

And that's it! That is how our amazing Email Automation robot works, end-to-end! 🎉
