import React, { useState } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";

interface Props {
  onSubmit: (text: string) => void;
  isLoading: boolean;
}

export default function Input({ onSubmit, isLoading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim()) return;
    onSubmit(value);
    setValue("");
  };

  return (
    <Box borderStyle="round" borderColor="green" paddingX={1}>
      <Text bold color="green">{">"} </Text>
      {isLoading ? (
        <Text color="gray">waiting for response...</Text>
      ) : (
        <TextInput value={value} onChange={setValue} onSubmit={handleSubmit} />
      )}
    </Box>
  );
}