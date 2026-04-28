import React, { useState } from "react";
import { Box } from "ink";
import { useInput } from "ink";
import Input from "./Input.js";
import Output from "./Output.js";
import CommandPalette from "./CommandPalette.js";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showPalette, setShowPalette] = useState(false);

  const handleSelectCommand = (cmd: string) => {
    setShowPalette(false);
    if (cmd === "new") {
      setMessages([]);
    } else if (cmd.startsWith("model:")) {
      console.log(`Switching to model: ${cmd.replace("model:", "")}`);
    }
  };

  useInput((input, key) => {
    if (showPalette) {
      if (key.escape) {
        setShowPalette(false);
      }
      return;
    }
    if (key.ctrl && input === "c") {
      const output = messages.map(m => m.content).join("\n");
      process.stdout.write(`\x1b]52;c;${Buffer.from(output).toString("base64")}\x07`);
    }
    if (input === "/") {
      setShowPalette(true);
    }
    if (key.ctrl && input === "1") {
      console.log("Switch to Anthropic model");
    }
    if (key.ctrl && input === "2") {
      console.log("Switch to OpenAI model");
    }
  });

  const handleSubmit = async (text: string) => {
    setMessages(prev => [...prev, { role: "user", content: text }]);
    setIsLoading(true);

    const response = await fetch("/dev/stdin", {
      method: "POST",
      body: JSON.stringify({ method: "chat", params: { message: text }, id: 1 }),
    });
    const data = await response.json();

    setMessages(prev => [...prev, { role: "assistant", content: data.result?.response ?? "" }]);
    setIsLoading(false);
  };

  return (
    <Box flexDirection="column" height={process.stdout.rows - 1}>
      {showPalette ? (
        <CommandPalette onSelect={handleSelectCommand} />
      ) : (
        <>
          <Box flexDirection="column" borderStyle="round" borderColor="green" padding={1}>
            <Output messages={messages} />
          </Box>
          <Input onSubmit={handleSubmit} isLoading={isLoading} />
        </>
      )}
    </Box>
  );
}