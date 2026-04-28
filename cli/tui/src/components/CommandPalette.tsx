import React, { useState } from "react";
import { Box, Text } from "ink";
import Select from "ink-select-input";

const COMMANDS = [
  { label: "New Session", value: "new" },
  { label: "Resume Session", value: "resume" },
  { label: "Model: Anthropic", value: "model:anthropic" },
  { label: "Model: OpenAI", value: "model:openai" },
];

interface Props {
  onSelect: (cmd: string) => void;
}

export default function CommandPalette({ onSelect }: Props) {
  const [selected, setSelected] = useState(0);

  const handleSelect = (item: { label: string; value: string }) => {
    onSelect(item.value);
  };

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" padding={1}>
      <Text bold>Command Palette</Text>
      <Select items={COMMANDS} onSelect={handleSelect} />
    </Box>
  );
}