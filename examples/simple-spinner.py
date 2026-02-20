import time

from bombshell import spin

with spin("Processing..."):
    time.sleep(2)

with spin("Processing...") as spinner:
    for i in range(20):
        spinner.message = f"Processing... ({i}/20)"

        if i == 10:  # simulate error
            spinner.message = f"Processing failed on iteration {i}"
            spinner.fail()
            break

        time.sleep(0.25)

    # spinner.ok() is implicit
