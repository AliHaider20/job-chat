from glob import glob

class ProfileLoader:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir

    def load_and_format_markdown(self, filename):
        data = ""
        seperator = "-------"*20 + "\n"
        md_files = glob(self.data_dir + "/*.md")
        for md_file in md_files:
            with open(md_file, "r", encoding="utf-8") as f:
                data += f.read()
                data += seperator

        return data